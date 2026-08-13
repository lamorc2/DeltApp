(function () {
  const css = `
    #admin-cog{position:relative;display:flex;align-items:center}
    #admin-cog-btn{
      width:28px;height:28px;border-radius:50%;
      background:transparent;border:1px solid var(--border);color:var(--gold);
      cursor:pointer;font-size:.85rem;line-height:1;display:flex;align-items:center;justify-content:center;
      padding:0;font-family:Cinzel,serif
    }
    #admin-cog-btn:hover{border-color:var(--gold);color:var(--gold)}
    #admin-cog-menu{
      display:none;position:absolute;top:calc(100% + 8px);right:0;min-width:240px;
      background:var(--surface,#1A0F21);border:1px solid var(--border-strong);
      border-radius:8px;padding:.4rem 0;z-index:400;
      box-shadow:0 8px 28px rgba(0,0,0,.45)
    }
    #admin-cog-menu.open{display:block}
    #admin-cog-menu a{
      display:block;padding:.65rem 1rem;text-decoration:none;color:var(--text);
      font-family:'Cinzel',serif;font-size:.65rem;letter-spacing:.12em;text-transform:uppercase
    }
    #admin-cog-menu a:hover{background:color-mix(in srgb, var(--gold) 10%, transparent);color:var(--gold)}
  `;

  window.initAdminCog = function (me) {
    if (!me || me.role !== 'admin' || document.getElementById('admin-cog')) return;
    const badge = document.querySelector('.topbar-user .user-badge');
    if (!badge) return;

    if (!document.getElementById('admin-cog-css')) {
      const style = document.createElement('style');
      style.id = 'admin-cog-css';
      style.textContent = css;
      document.head.appendChild(style);
    }

    const wrap = document.createElement('div');
    wrap.id = 'admin-cog';
    wrap.innerHTML =
      '<button type="button" id="admin-cog-btn" aria-label="Admin settings">⚙</button>' +
      '<div id="admin-cog-menu">' +
        '<a href="/users">User Management</a>' +
        '<a href="/setup">Chapter Style</a>' +
        '<a href="/archive">Archive Current Term</a>' +
        '<a href="/archives">View Archived Terms</a>' +
      '</div>';
    const help = document.getElementById('bug-help-btn');
    if (help) {
      help.parentNode.insertBefore(wrap, help.nextSibling);
    } else {
      badge.parentNode.insertBefore(wrap, badge);
    }

    const btn = wrap.querySelector('#admin-cog-btn');
    const menu = wrap.querySelector('#admin-cog-menu');
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      menu.classList.toggle('open');
    });
    document.addEventListener('click', function () {
      menu.classList.remove('open');
    });
    menu.addEventListener('click', function (e) { e.stopPropagation(); });
  };
})();
