[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SqlServer,
    [string]$Warehouse = 'QuocDatDWH',
    [string]$CubeDatabase = 'QuocDatSales',
    [string]$Provider = 'MSOLEDBSQL',
    [string]$AmoAssembly,
    [string]$OutputPath = (Join-Path $PSScriptRoot '../instance/quocdat-sales.xmla'),
    [string]$AnalysisServer,
    [switch]$TrustServerCertificate
)

$ErrorActionPreference = 'Stop'
if ($CubeDatabase -notmatch '^[A-Za-z][A-Za-z0-9_]*$') {
    throw 'CubeDatabase must contain letters, digits, or underscores and begin with a letter.'
}
if (!$AmoAssembly) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $AmoAssembly = & $vswhere -products '*' -prerelease -find 'Common7\IDE\CommonExtensions\Microsoft\SSAS\Microsoft.AnalysisServices.dll' |
            Select-Object -First 1
    }
    if (!$AmoAssembly) {
        throw 'Install Microsoft Analysis Services Projects for Visual Studio, or pass -AmoAssembly.'
    }
}
[void][Reflection.Assembly]::LoadFrom((Resolve-Path -LiteralPath $AmoAssembly).Path)

$definitions = [ordered]@{
    ssas_fact_sales = [ordered]@{
        sales_key = [long]; date_key = [long]; product_key = [long]; customer_key = [long]
        platform_key = [long]; order_key = [long]; quantity = [long]
        gross_amount = [double]; discount_amount = [double]; net_amount = [double]
    }
    ssas_dim_date = [ordered]@{
        date_key = [long]; full_date = 12; year_number = [long]; quarter_key = [long]
        month_key = [long]; quarter_label = 8; month_name = 20
    }
    ssas_dim_product = [ordered]@{ product_key = [long]; category_name = 300 }
    ssas_dim_customer = [ordered]@{ customer_key = [long]; customer_city = 200 }
    ssas_dim_platform = [ordered]@{ platform_key = [long]; platform_name = 100 }
}

$database = [Microsoft.AnalysisServices.Database]::new($CubeDatabase, $CubeDatabase)
$definitionServer = [Microsoft.AnalysisServices.Server]::new()
[void]$definitionServer.Databases.Add($database)
$connection = [System.Data.Common.DbConnectionStringBuilder]::new()
$connection['Provider'] = $Provider
$connection['Data Source'] = $SqlServer
$connection['Initial Catalog'] = $Warehouse
$connection['Integrated Security'] = 'SSPI'
if ($TrustServerCertificate) {
    $connection['Trust Server Certificate'] = 'True'
}
$source = [Microsoft.AnalysisServices.RelationalDataSource]::new('QuocDat Warehouse', 'QuocDatWarehouse')
$source.ConnectionString = $connection.ConnectionString
$source.ImpersonationInfo = [Microsoft.AnalysisServices.ImpersonationInfo]::new('ImpersonateServiceAccount')
[void]$database.DataSources.Add($source)

$dsv = [Microsoft.AnalysisServices.DataSourceView]::new()
$dsv.Name = 'QuocDat Sales Source'
$dsv.ID = 'QuocDatSalesSource'
$dsv.DataSourceID = $source.ID
$dataSet = [System.Data.DataSet]::new('QuocDatSalesSource')
foreach ($tableName in $definitions.Keys) {
    $table = [System.Data.DataTable]::new($tableName)
    $table.ExtendedProperties['DbSchemaName'] = 'dbo'
    $table.ExtendedProperties['DbTableName'] = $tableName
    $table.ExtendedProperties['FriendlyName'] = $tableName
    $table.ExtendedProperties['TableType'] = 'View'
    foreach ($columnName in $definitions[$tableName].Keys) {
        $spec = $definitions[$tableName][$columnName]
        $type = if ($spec -is [type]) { $spec } else { [string] }
        $column = $table.Columns.Add($columnName, $type)
        if ($type -eq [string]) { $column.MaxLength = $spec }
        $column.AllowDBNull = $false
    }
    $table.PrimaryKey = @($table.Columns[0])
    $dataSet.Tables.Add($table)
}
foreach ($tableName in $definitions.Keys | Where-Object { $_ -ne 'ssas_fact_sales' }) {
    $parent = $dataSet.Tables[$tableName].Columns[0]
    $child = $dataSet.Tables['ssas_fact_sales'].Columns[$parent.ColumnName]
    [void]$dataSet.Relations.Add("$($parent.ColumnName)_sales", $parent, $child, $false)
}
$dsv.Schema = $dataSet
[void]$database.DataSourceViews.Add($dsv)

function Get-DataItem([string]$TableName, [string]$ColumnName) {
    $spec = $definitions[$TableName][$ColumnName]
    if ($spec -eq [long]) {
        return [Microsoft.AnalysisServices.DataItem]::new($TableName, $ColumnName, [System.Data.OleDb.OleDbType]::BigInt)
    }
    if ($spec -eq [double]) {
        return [Microsoft.AnalysisServices.DataItem]::new($TableName, $ColumnName, [System.Data.OleDb.OleDbType]::Double)
    }
    return [Microsoft.AnalysisServices.DataItem]::new($TableName, $ColumnName, [System.Data.OleDb.OleDbType]::WChar, $spec)
}

function Add-Attribute($Dimension, [string]$Name, [string]$Table, [string]$Key, [string]$Display) {
    $attribute = [Microsoft.AnalysisServices.DimensionAttribute]::new($Name, $Name)
    [void]$attribute.KeyColumns.Add((Get-DataItem $Table $Key))
    if ($Display) { $attribute.NameColumn = Get-DataItem $Table $Display }
    [void]$Dimension.Attributes.Add($attribute)
    return $attribute
}

$dimensionSpecs = @(
    @{Name='Date'; Table='ssas_dim_date'; Key='date_key'; Caption='full_date'; Leaf='Date'},
    @{Name='Product'; Table='ssas_dim_product'; Key='product_key'; Caption=''; Leaf='Product Key'; Group='Category'; GroupColumn='category_name'},
    @{Name='Location'; Table='ssas_dim_customer'; Key='customer_key'; Caption=''; Leaf='Customer Key'; Group='City'; GroupColumn='customer_city'},
    @{Name='Platform'; Table='ssas_dim_platform'; Key='platform_key'; Caption='platform_name'; Leaf='Platform'}
)
$cube = [Microsoft.AnalysisServices.Cube]::new('Sales', 'Sales')
$cube.Source = [Microsoft.AnalysisServices.DataSourceViewBinding]::new($dsv.ID)
$cube.StorageMode = 'Molap'
[void]$database.Cubes.Add($cube)
foreach ($spec in $dimensionSpecs) {
    $dimension = [Microsoft.AnalysisServices.Dimension]::new($spec.Name, $spec.Name)
    $dimension.Source = [Microsoft.AnalysisServices.DataSourceViewBinding]::new($dsv.ID)
    [void]$database.Dimensions.Add($dimension)
    $leaf = Add-Attribute $dimension $spec.Leaf $spec.Table $spec.Key $spec.Caption
    $leaf.Usage = 'Key'
    if ($spec.Group) {
        $leaf.AttributeHierarchyVisible = $false
        $group = Add-Attribute $dimension $spec.Group $spec.Table $spec.GroupColumn ''
        [void]$leaf.AttributeRelationships.Add($group.ID)
    }
    if ($spec.Name -eq 'Date') {
        $dimension.Type = 'Time'
        $leaf.Type = 'Days'
        $year = Add-Attribute $dimension 'Year' $spec.Table 'year_number' ''
        $quarter = Add-Attribute $dimension 'Quarter' $spec.Table 'quarter_key' 'quarter_label'
        $month = Add-Attribute $dimension 'Month' $spec.Table 'month_key' 'month_name'
        $year.Type = 'Years'
        $quarter.Type = 'Quarters'
        $month.Type = 'Months'
        [void]$leaf.AttributeRelationships.Add($month.ID)
        [void]$month.AttributeRelationships.Add($quarter.ID)
        [void]$quarter.AttributeRelationships.Add($year.ID)
        $hierarchy = [Microsoft.AnalysisServices.Hierarchy]::new('Calendar', 'Calendar')
        foreach ($attribute in @($year, $quarter, $month, $leaf)) {
            $level = [Microsoft.AnalysisServices.Level]::new($attribute.Name, $attribute.ID)
            $level.SourceAttributeID = $attribute.ID
            [void]$hierarchy.Levels.Add($level)
        }
        [void]$dimension.Hierarchies.Add($hierarchy)
    }
    [void]$cube.Dimensions.Add([Microsoft.AnalysisServices.CubeDimension]::new($dimension.ID))
}

function Add-MeasureGroup([string]$Name) {
    $group = [Microsoft.AnalysisServices.MeasureGroup]::new($Name, ($Name -replace ' ', ''))
    [void]$cube.MeasureGroups.Add($group)
    [void]$group.Dimensions.Clear()
    foreach ($spec in $dimensionSpecs) {
        $binding = [Microsoft.AnalysisServices.RegularMeasureGroupDimension]::new($spec.Name)
        $attribute = $binding.Attributes.Add($spec.Leaf)
        $attribute.Type = 'Granularity'
        [void]$attribute.KeyColumns.Add((Get-DataItem 'ssas_fact_sales' $spec.Key))
        [void]$group.Dimensions.Add($binding)
    }
    $partition = [Microsoft.AnalysisServices.Partition]::new($Name, $group.ID)
    $partition.Source = [Microsoft.AnalysisServices.TableBinding]::new($source.ID, 'dbo', 'ssas_fact_sales')
    $partition.StorageMode = 'Molap'
    [void]$group.Partitions.Add($partition)
    return $group
}

function Add-Measure($Group, [string]$Name, [string]$Column, [string]$Aggregate) {
    $measure = [Microsoft.AnalysisServices.Measure]::new()
    $measure.Name = $Name
    $measure.ID = $Name -replace ' ', ''
    $measure.AggregateFunction = $Aggregate
    $measure.Source = Get-DataItem 'ssas_fact_sales' $Column
    $measure.FormatString = if ($definitions['ssas_fact_sales'][$Column] -eq [double]) { '#,##0.00' } else { '#,##0' }
    [void]$Group.Measures.Add($measure)
}

$sales = Add-MeasureGroup 'Sales Lines'
Add-Measure $sales 'Sales Line Count' 'sales_key' 'Count'
Add-Measure $sales 'Units Sold' 'quantity' 'Sum'
Add-Measure $sales 'Gross Revenue' 'gross_amount' 'Sum'
Add-Measure $sales 'Discount Amount' 'discount_amount' 'Sum'
Add-Measure $sales 'Net Revenue' 'net_amount' 'Sum'
Add-Measure (Add-MeasureGroup 'Orders') 'Order Count' 'order_key' 'DistinctCount'
Add-Measure (Add-MeasureGroup 'Customers') 'Customer Count' 'customer_key' 'DistinctCount'
$cube.DefaultMeasure = '[Measures].[Net Revenue]'
$mdxScript = [Microsoft.AnalysisServices.MdxScript]::new('Calculations', 'Calculations')
$mdx = @'
CALCULATE;
CREATE MEMBER CURRENTCUBE.[Measures].[Average Selling Price] AS
    IIF([Measures].[Units Sold] = 0, NULL, [Measures].[Net Revenue] / [Measures].[Units Sold]),
    FORMAT_STRING = '#,##0.00', VISIBLE = 1;
'@
[void]$mdxScript.Commands.Add([Microsoft.AnalysisServices.Command]::new($mdx))
[void]$cube.MdxScripts.Add($mdxScript)

$fullPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
$settings = [System.Xml.XmlWriterSettings]::new()
$settings.Indent = $true
$writer = [System.Xml.XmlWriter]::Create($fullPath, $settings)
try {
    [Microsoft.AnalysisServices.Scripter]::WriteCreate($writer, $definitionServer, $database, $true, $false)
} finally {
    $writer.Dispose()
    $definitionServer.Dispose()
}
Write-Output "Saved XMLA to $fullPath"

function Invoke-Xmla($Server, [string]$CommandText) {
    foreach ($response in $Server.Execute($CommandText)) {
        foreach ($message in $response.Messages) {
            if ($message.GetType().Name -eq 'XmlaError') { throw $message.Description }
            Write-Warning $message.Description
        }
    }
}

if ($AnalysisServer) {
    $server = [Microsoft.AnalysisServices.Server]::new()
    try {
        $server.Connect($AnalysisServer)
        if ($server.Databases.Contains($CubeDatabase)) {
            throw "Analysis Services already contains $CubeDatabase. Use a new CubeDatabase to deploy a separate model."
        }
        $document = [xml][IO.File]::ReadAllText($fullPath)
        Invoke-Xmla $server $document.DocumentElement.OuterXml
        $process = "<Process xmlns='http://schemas.microsoft.com/analysisservices/2003/engine'><Object><DatabaseID>$CubeDatabase</DatabaseID></Object><Type>ProcessFull</Type></Process>"
        Invoke-Xmla $server $process
        Write-Output "Deployed and processed $CubeDatabase on $AnalysisServer"
    } finally {
        $server.Dispose()
    }
}
