(() => {
  // 1. Mobile Navigation Toggle
  const navToggle = document.querySelector('.nav-toggle');
  const siteNav = document.querySelector('#site-nav');
  if (navToggle && siteNav) {
    navToggle.addEventListener('click', () => {
      const open = siteNav.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(open));
      navToggle.textContent = open ? 'Close' : 'Menu';
    });
  }

  // 2. Flash Dismiss
  document.querySelectorAll('[data-dismiss-flash]').forEach((button) => {
    button.addEventListener('click', () => button.closest('.flash')?.remove());
  });

  // 3. Header Search Trending Popover
  const searchWrap = document.querySelector('[data-search-wrap]');
  if (searchWrap) {
    const searchInput = searchWrap.querySelector('[data-search-input]');
    const popover = searchWrap.querySelector('[data-search-popover]');
    if (searchInput && popover) {
      searchInput.addEventListener('focus', () => { popover.hidden = false; });
      document.addEventListener('click', (e) => {
        if (!searchWrap.contains(e.target)) popover.hidden = true;
      });
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') popover.hidden = true;
      });
    }
  }

  // 4. Hero Interactive Spotlight Deck & Tabs
  const spotlight = document.querySelector('[data-spotlight]');
  if (spotlight) {
    const tabBtns = spotlight.querySelectorAll('[data-tab-target]');
    const tabPanes = spotlight.querySelectorAll('[data-tab-pane]');
    tabBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.tabTarget;
        tabBtns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-selected', String(active));
        });
        tabPanes.forEach((p) => p.classList.toggle('active', p.dataset.tabPane === target));
      });
    });

    const slides = Array.from(spotlight.querySelectorAll('[data-slide]'));
    const dots = Array.from(spotlight.querySelectorAll('[data-slide-dot]'));
    if (slides.length > 1) {
      let current = 0;
      const showSlide = (idx) => {
        current = (idx + slides.length) % slides.length;
        slides.forEach((s, i) => s.classList.toggle('active', i === current));
        dots.forEach((d, i) => d.classList.toggle('active', i === current));
      };
      spotlight.querySelector('[data-slide-prev]')?.addEventListener('click', () => showSlide(current - 1));
      spotlight.querySelector('[data-slide-next]')?.addEventListener('click', () => showSlide(current + 1));
      dots.forEach((d) => d.addEventListener('click', () => showSlide(Number(d.dataset.slideDot || 0))));

      let paused = false;
      spotlight.addEventListener('mouseenter', () => { paused = true; });
      spotlight.addEventListener('mouseleave', () => { paused = false; });
      window.setInterval(() => {
        if (!paused && spotlight.querySelector('[data-tab-pane="spotlight"]')?.classList.contains('active')) {
          showSlide(current + 1);
        }
      }, 5500);
    }
  }

  // 5. Product Quick View Modal
  const qvModal = document.getElementById('quick-view-modal');
  if (qvModal) {
    const qvMedia = qvModal.querySelector('[data-qv-media]');
    const qvPlatform = qvModal.querySelector('[data-qv-platform]');
    const qvCode = qvModal.querySelector('[data-qv-code]');
    const qvCategory = qvModal.querySelector('[data-qv-category]');
    const qvName = qvModal.querySelector('[data-qv-name]');
    const qvMeta = qvModal.querySelector('[data-qv-meta]');
    const qvPrice = qvModal.querySelector('[data-qv-price]');
    const qvListPrice = qvModal.querySelector('[data-qv-list-price]');
    const qvDiscount = qvModal.querySelector('[data-qv-discount]');
    const qvStock = qvModal.querySelector('[data-qv-stock]');
    const qvLink = qvModal.querySelector('[data-qv-link]');

    const closeModal = () => { qvModal.hidden = true; };

    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-quick-view]');
      if (!btn) return;
      const card = btn.closest('.product-card');
      if (!card) return;
      const d = card.dataset;

      qvMedia.innerHTML = '';
      if (d.productImage) {
        const img = document.createElement('img');
        img.src = d.productImage;
        img.alt = d.productName || '';
        qvMedia.appendChild(img);
      } else {
        const clonedStudio = card.querySelector('.studio-fallback')?.cloneNode(true);
        if (clonedStudio) {
          clonedStudio.classList.add('studio-fallback-lg');
          clonedStudio.style.display = 'flex';
          qvMedia.appendChild(clonedStudio);
        }
      }

      qvPlatform.textContent = d.productPlatform || '';
      qvPlatform.className = `qv-platform platform-flag platform-${(d.productPlatform || '').toLowerCase()}`;
      qvCode.textContent = d.productCode || '';
      qvCategory.textContent = d.productCategory || '';
      qvName.textContent = d.productName || '';

      const ratingNum = parseFloat(d.productRating || '0');
      qvMeta.innerHTML = ratingNum > 0
        ? `<span class="star-pill">★ ${d.productRating}</span> <span>${d.productReviews} reviews</span> <span>· ${d.productSold} sold</span>`
        : `<span class="verified-pill">Curated Marketplace</span> <span>· ${d.productSold} sold</span>`;

      qvPrice.textContent = d.productPrice || '';
      qvListPrice.textContent = d.productListPrice || '';
      if (d.productDiscount) {
        qvDiscount.textContent = `-${d.productDiscount}%`;
        qvDiscount.hidden = false;
      } else {
        qvDiscount.hidden = true;
      }

      const stock = Number(d.productStock || 0);
      qvStock.textContent = stock > 0 ? `${stock} units ready to ship` : 'Currently out of stock';
      qvStock.className = `qv-stock ${stock > 0 ? 'in' : 'out'}`;
      qvLink.href = d.productUrl || '#';

      qvModal.hidden = false;
    });

    qvModal.querySelectorAll('[data-qv-close]').forEach((el) => el.addEventListener('click', closeModal));
    qvModal.addEventListener('click', (e) => { if (e.target === qvModal) closeModal(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !qvModal.hidden) closeModal(); });
  }

  // 6. Quantity Stepper on Product Detail
  document.querySelectorAll('[data-qty-stepper]').forEach((stepper) => {
    const input = stepper.querySelector('input[type="number"]');
    const dec = stepper.querySelector('[data-qty-dec]');
    const inc = stepper.querySelector('[data-qty-inc]');
    if (!input) return;
    const min = Number(input.min || 1);
    const max = Number(input.max || 9999);
    dec?.addEventListener('click', () => {
      input.value = String(Math.max(min, (Number(input.value) || min) - 1));
    });
    inc?.addEventListener('click', () => {
      input.value = String(Math.min(max, (Number(input.value) || min) + 1));
    });
  });

  // 7. Back to Top
  const backToTop = document.getElementById('back-to-top');
  if (backToTop) {
    const toggleBackTop = () => { backToTop.hidden = window.scrollY < 420; };
    window.addEventListener('scroll', toggleBackTop, { passive: true });
    backToTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  }

  // 8. Demo Account Quick-Fill (Login Page)
  document.querySelectorAll('[data-demo-fill]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const form = document.querySelector('.auth-card form');
      if (!form) return;
      const emailInput = form.querySelector('input[name="email"]');
      const passInput = form.querySelector('input[name="password"]');
      if (emailInput) emailInput.value = btn.dataset.email || '';
      if (passInput) passInput.value = btn.dataset.password || '';
      emailInput?.focus();
    });
  });

  // 9. Procurement Form (Live Product Lookup & Totals)
  const procurementForm = document.querySelector('[data-procurement-form]');
  if (!procurementForm) return;

  const lines = procurementForm.querySelector('[data-lines]');
  const template = document.querySelector('#procurement-line-template');
  const documentTotal = procurementForm.querySelector('[data-document-total]');
  const currency = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'VND',
    currencyDisplay: 'code',
    maximumFractionDigits: 0,
  });
  let lookupTimer;

  const numberValue = (input) => {
    const value = Number(input?.value || 0);
    return Number.isFinite(value) ? value : 0;
  };

  const updateTotals = () => {
    let total = 0;
    lines.querySelectorAll('[data-line]').forEach((line) => {
      const lineTotal = numberValue(line.querySelector('[data-quantity]')) *
        numberValue(line.querySelector('[data-unit-cost]'));
      total += lineTotal;
      const output = line.querySelector('[data-line-total]');
      if (output) output.textContent = currency.format(lineTotal);
    });
    if (documentTotal) documentTotal.textContent = currency.format(total);
  };

  const clearSuggestions = (line) => line.querySelector('.product-suggestions')?.remove();

  const chooseProduct = (line, product) => {
    const codeInput = line.querySelector('[data-product-code]');
    const nameOutput = line.querySelector('[data-product-name]');
    const costInput = line.querySelector('[data-unit-cost]');
    codeInput.value = product.product_code;
    nameOutput.textContent = `${product.name} · stock ${product.stock}`;
    nameOutput.classList.add('resolved');
    if (numberValue(costInput) === 0) {
      costInput.value = String(Math.max(100, Math.round(product.current_price * 0.65 / 100) * 100));
    }
    clearSuggestions(line);
    updateTotals();
  };

  const lookupProducts = async (line, query) => {
    clearSuggestions(line);
    if (query.trim().length < 2) return;
    try {
      const response = await fetch(`/api/products?q=${encodeURIComponent(query.trim())}`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) return;
      const products = await response.json();
      if (!products.length) {
        line.querySelector('[data-product-name]').textContent = 'No products found';
        return;
      }
      const list = document.createElement('div');
      list.className = 'product-suggestions';
      list.setAttribute('role', 'listbox');
      products.slice(0, 7).forEach((product) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.setAttribute('role', 'option');
        option.innerHTML = `<strong>${product.product_code}</strong><span>${product.name}</span><small>Stock ${product.stock}</small>`;
        option.addEventListener('click', () => chooseProduct(line, product));
        list.appendChild(option);
      });
      line.querySelector('[data-product-code]').closest('label').appendChild(list);
    } catch (_error) {
      line.querySelector('[data-product-name]').textContent = 'Product lookup is unavailable';
    }
  };

  procurementForm.addEventListener('input', (event) => {
    if (event.target.matches('[data-quantity], [data-unit-cost]')) updateTotals();
    if (event.target.matches('[data-product-code]')) {
      const line = event.target.closest('[data-line]');
      line.querySelector('[data-product-name]').textContent = 'Searching…';
      line.querySelector('[data-product-name]').classList.remove('resolved');
      window.clearTimeout(lookupTimer);
      lookupTimer = window.setTimeout(() => lookupProducts(line, event.target.value), 260);
    }
  });

  procurementForm.addEventListener('click', (event) => {
    const addButton = event.target.closest('[data-add-line]');
    if (addButton && template) {
      lines.appendChild(template.content.cloneNode(true));
      lines.lastElementChild?.querySelector('[data-product-code]')?.focus();
      updateTotals();
      return;
    }

    const removeButton = event.target.closest('[data-remove-line]');
    if (removeButton) {
      const allLines = lines.querySelectorAll('[data-line]');
      const line = removeButton.closest('[data-line]');
      if (allLines.length === 1) {
        line.querySelectorAll('input').forEach((input) => {
          input.value = input.matches('[data-quantity]') ? '1' : '0';
        });
        line.querySelector('[data-product-name]').textContent = 'No product selected';
      } else {
        line.remove();
      }
      updateTotals();
    }
  });

  document.addEventListener('click', (event) => {
    procurementForm.querySelectorAll('[data-line]').forEach((line) => {
      if (!line.contains(event.target)) clearSuggestions(line);
    });
  });

  updateTotals();
})();

// Keep the active backoffice destination visible in the compact mobile rail.
(() => {
  const nav = document.querySelector('.dashboard-sidebar nav');
  const activeLink = nav?.querySelector('a.active');
  if (!nav || !activeLink || !window.matchMedia('(max-width: 720px)').matches) return;
  nav.scrollLeft = activeLink.offsetLeft - (nav.clientWidth - activeLink.clientWidth) / 2;
})();
