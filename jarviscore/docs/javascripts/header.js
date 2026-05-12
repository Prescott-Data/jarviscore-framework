/* JarvisCore Docs — Header enhancements
   - Injects version chip after site title
   - Injects GitHub repo + stars widget (Prescott-Data/JarvisCore ★ N)
   - Moves theme palette toggle to far-right
   - Opens external tabs in new window
*/
document.addEventListener('DOMContentLoaded', function () {

  /* ── 1. Version chip ─────────────────────────────────── */
  var title = document.querySelector('.md-header__title');
  /* Read version from mkdocs.yml extra.version (injected by Material as
     __md_extra). Falls back to __init__.__version__ pattern in the chip. */
  var configVersion = (typeof __md_extra !== 'undefined' && __md_extra.version)
    ? 'v' + __md_extra.version
    : 'v1.1.0';
  var chip;
  if (title) {
    chip = document.createElement('span');
    chip.className = 'jc-version-chip';
    chip.textContent = configVersion;
    title.insertAdjacentElement('afterend', chip);
  }

  /* Fetch live version from GitHub tags */
  fetch('https://api.github.com/repos/Prescott-Data/jarviscore-framework/tags')
    .then(function (r) { return r.json(); })
    .then(function (tags) {
      if (Array.isArray(tags) && tags.length > 0) {
        var latestVersion = tags[0].name;
        // Update nav chip
        if (chip) chip.textContent = latestVersion;
        
        // Update hero badge
        var heroBadge = document.getElementById('jc-hero-version-badge');
        if (heroBadge) {
          heroBadge.innerHTML = latestVersion + ' &middot; Apache 2.0 &middot; Production Ready';
        }
      }
    })
    .catch(function () {});

  /* ── 2. GitHub stars widget ─────────────────────────── */
  var inner = document.querySelector('.md-header__inner');
  var palette = document.querySelector('form[data-md-component="palette"]');
  if (inner && palette) {
    var ghBtn = document.createElement('a');
    ghBtn.href = 'https://github.com/Prescott-Data/jarviscore-framework';
    ghBtn.target = '_blank';
    ghBtn.rel = 'noopener noreferrer';
    ghBtn.className = 'jc-gh-stars-btn';
    ghBtn.setAttribute('aria-label', 'Star JarvisCore on GitHub');
    ghBtn.innerHTML =
      '<span class="jc-gh-repo">Prescott-Data/JarvisCore</span>' +
      '<span class="jc-gh-sep">★</span>' +
      '<span class="jc-stars-count">—</span>';

    /* Insert widget, then move palette to absolute end (far right) */
    inner.insertBefore(ghBtn, palette);
    inner.appendChild(palette);
  }

  /* ── 3. Async star count ────────────────────────────── */
  fetch('https://api.github.com/repos/Prescott-Data/jarviscore-framework')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var el = document.querySelector('.jc-stars-count');
      if (el && typeof data.stargazers_count === 'number') {
        var n = data.stargazers_count;
        el.textContent = n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
      }
    })
    .catch(function () {});

  /* ── 4. External tabs → new window ────────────────────── */
  var EXT = ['https://developers.prescottdata.io', 'https://discord.gg'];
  document.querySelectorAll('.md-tabs__link').forEach(function (link) {
    var href = link.getAttribute('href') || '';
    if (EXT.some(function (p) { return href.startsWith(p); })) {
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
    }
  });

  /* ── 5. (removed) — Material's context-aware drawer is correct ── */

});
