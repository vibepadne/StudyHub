(function () {
  const eyeSvg = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/></svg>';
  const eyeOffSvg = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M17.94 17.94A10.94 10.94 0 0112 20c-7 0-11-8-11-8a20.77 20.77 0 014.22-5.18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M9.53 9.53A3 3 0 0012 12a3 3 0 002.47-1.27" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M14.12 14.12L9.88 9.88" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M10.58 10.58L3 3m18 18l-4.35-4.35" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

  function enhanceField(input) {
    if (input.dataset.eyeEnhanced) return;
    if (input.closest('.password-field')) {
      // Already wrapped manually, just attach toggle if missing
      const field = input.closest('.password-field');
      let btn = field.querySelector('.password-toggle');
      if (!btn) {
        btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'password-toggle';
        btn.setAttribute('aria-label', 'Show password');
        btn.innerHTML = eyeSvg;
        field.appendChild(btn);
      }
      attachToggle(input, btn);
      input.dataset.eyeEnhanced = '1';
      return;
    }
    // Auto-wrap bare password inputs
    const wrapper = document.createElement('div');
    wrapper.className = 'password-field';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'password-toggle';
    btn.setAttribute('aria-label', 'Show password');
    btn.setAttribute('tabindex', '0');
    btn.innerHTML = eyeSvg;
    wrapper.appendChild(btn);
    attachToggle(input, btn);
    input.dataset.eyeEnhanced = '1';
  }

  function attachToggle(input, btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      const isPassword = input.type === 'password';
      input.type = isPassword ? 'text' : 'password';
      btn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');
      btn.innerHTML = isPassword ? eyeOffSvg : eyeSvg;
      // keep focus
      input.focus();
      const val = input.value;
      input.value = '';
      input.value = val;
    });
  }

  function init() {
    document.querySelectorAll('input[type=\"password\"]').forEach(enhanceField);
    // Also handle inputs that are password-field contained text that was toggled previously
    // Observe added nodes for dynamically created forms
    const observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        m.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches && node.matches('input[type=\"password\"]')) enhanceField(node);
          node.querySelectorAll && node.querySelectorAll('input[type=\"password\"]').forEach(enhanceField);
          // handle wrapped fields with text type that were previously password
          if (node.matches && node.matches('.password-field')) {
            const inp = node.querySelector('input');
            if (inp) enhanceField(inp);
          }
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
