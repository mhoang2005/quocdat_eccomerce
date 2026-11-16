-- Run in the QuocDat warehouse database, using a SQL Server administrator.
DECLARE @principal sysname = N'NT SERVICE\MSSQLServerOLAPService';
DECLARE @quoted nvarchar(258) = QUOTENAME(@principal);
DECLARE @statement nvarchar(max);

IF SUSER_ID(@principal) IS NULL
BEGIN
    SET @statement = N'CREATE LOGIN ' + @quoted + N' FROM WINDOWS;';
    EXEC sys.sp_executesql @statement;
END;
IF DATABASE_PRINCIPAL_ID(@principal) IS NULL
BEGIN
    SET @statement = N'CREATE USER ' + @quoted + N' FOR LOGIN ' + @quoted + N';';
    EXEC sys.sp_executesql @statement;
END;

SET @statement =
    N'GRANT SELECT ON dbo.ssas_fact_sales TO ' + @quoted + N';' +
    N'GRANT SELECT ON dbo.ssas_dim_date TO ' + @quoted + N';' +
    N'GRANT SELECT ON dbo.ssas_dim_product TO ' + @quoted + N';' +
    N'GRANT SELECT ON dbo.ssas_dim_customer TO ' + @quoted + N';' +
    N'GRANT SELECT ON dbo.ssas_dim_platform TO ' + @quoted + N';';
EXEC sys.sp_executesql @statement;
