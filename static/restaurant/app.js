'use strict';
(() => {
  const toggle = document.querySelector('[data-nav-toggle]');
  const sidebar = document.querySelector('.sidebar');
  const backdrop = document.querySelector('[data-nav-backdrop]');
  const closeNav = () => {
    sidebar?.classList.remove('open');
    toggle?.setAttribute('aria-expanded', 'false');
    if (backdrop) backdrop.hidden = true;
  };
  toggle?.addEventListener('click', () => {
    const open = sidebar.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
    if (backdrop) backdrop.hidden = !open;
  });
  backdrop?.addEventListener('click', closeNav);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeNav(); });
  document.querySelectorAll('[data-print-receipt]').forEach(button => button.addEventListener('click', () => window.print()));
  const vegToggle = document.querySelector('input[name=veg]');
  vegToggle?.addEventListener('change', () => vegToggle.form?.requestSubmit());

  document.querySelectorAll('img[data-food-image]').forEach(img => {
    const fallback = () => {
      img.classList.add('image-failed');
      img.alt = img.alt || 'Restaurant dish';
      img.removeAttribute('srcset');
      img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300"%3E%3Crect width="400" height="300" fill="%23282b27"/%3E%3Cg fill="none" stroke="%23b5835e" stroke-width="3"%3E%3Ccircle cx="200" cy="150" r="55"/%3E%3Ccircle cx="200" cy="150" r="42"/%3E%3Cpath d="M115 100v100m-10-100v35q10 15 20 0v-35m160 0v100m0-100q-25 35 0 55"/%3E%3C/g%3E%3C/svg%3E';
    };
    img.addEventListener('error', fallback, { once: true });
    if (img.complete && !img.naturalWidth) fallback();
  });

  document.querySelectorAll('[data-quantity-control]').forEach(group => {
    const input = group.querySelector('input[type=number]');
    if (!input) return;
    group.querySelectorAll('[data-step]').forEach(button => {
      button.addEventListener('click', () => {
        const next = (Number(input.value) || 0) + Number(button.dataset.step);
        const min = Number(input.min || 0), max = Number(input.max || 20);
        input.value = Math.min(max, Math.max(min, next));
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });
  });

  document.querySelectorAll('[data-table-choice]').forEach(button => {
    button.addEventListener('click', () => {
      const input = document.querySelector('[name=table_number]');
      if (!input) return;
      input.value = button.dataset.tableChoice;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      document.querySelectorAll('[data-table-choice]').forEach(other => {
        const active = other === button;
        other.classList.toggle('active', active);
        other.setAttribute('aria-pressed', String(active));
      });
    });
  });

  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
  document.querySelectorAll('form[data-submit-once]').forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented || !form.checkValidity()) return;
      const button = event.submitter;
      if (!button) return;
      if (button.dataset.submitting === 'true') { event.preventDefault(); return; }
      button.dataset.submitting = 'true';
      button.setAttribute('aria-disabled', 'true');
      button.classList.add('submitting');
      // Do not disable the button: its name/value can be part of the submitted action.
      window.setTimeout(() => { button.dataset.submitting = 'false'; button.removeAttribute('aria-disabled'); button.classList.remove('submitting'); }, 20000);
    });
  });

  const totalsForm = document.querySelector('[data-worker-form]');
  if (totalsForm) {
    const update = () => {
      let amount = 0, count = 0;
      totalsForm.querySelectorAll('input[data-price]').forEach(input => {
        const qty = Math.max(0, Number(input.value) || 0);
        count += qty; amount += qty * Number(input.dataset.price || 0);
      });
      document.querySelectorAll('[data-worker-total]').forEach(el => { el.textContent = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(amount / 100); });
      document.querySelectorAll('[data-worker-count]').forEach(el => { el.textContent = count + (count === 1 ? ' item selected' : ' items selected'); });
    };
    totalsForm.addEventListener('input', update); update();
  }

  const live = document.querySelector('[data-live-url]');
  const notice = document.querySelector('[data-freshness-notice]');
  if (live && notice && live.dataset.liveUrl) {
    let initial = null;
    const connection = document.createElement('p');
    connection.className = 'live-connection small muted';
    connection.setAttribute('role', 'status');
    connection.textContent = 'Checking for order updates…';
    live.append(connection);
    const poll = async () => {
      if (document.hidden) return;
      try {
        const response = await fetch(live.dataset.liveUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' }, cache: 'no-store' });
        if (!response.ok) throw new Error('Update check unavailable');
        const value = await response.json();
        const signature = JSON.stringify(value);
        if (initial === null) initial = signature;
        else if (signature !== initial) notice.hidden = false;
        connection.textContent = 'Order updates checked. This page checks again every 20 seconds.';
        connection.classList.remove('connection-error');
      } catch (_) {
        connection.textContent = 'Updates are unavailable. Your view may be out of date. Reconnect and refresh this page.';
        connection.classList.add('connection-error');
      }
    };
    poll(); window.setInterval(poll, 20000);
  }
})();
