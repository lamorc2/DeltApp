(function () {
  const STYLE = `
#bug-help-btn{width:28px;height:28px;border-radius:50%;border:1px solid var(--border);background:transparent;color:var(--gold);font-family:Cinzel,serif;font-size:.85rem;cursor:pointer;flex-shrink:0;line-height:1;padding:0}
#bug-help-btn:hover{border-color:var(--gold);background:color-mix(in srgb,var(--gold) 12%,transparent)}
#bug-help-overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;z-index:800;padding:1rem}
#bug-help-overlay.show{display:flex}
#bug-help-modal{background:var(--surface,#1A0F21);border:1px solid var(--border-strong);border-radius:8px;width:100%;max-width:420px;padding:1.35rem 1.5rem}
#bug-help-modal h2{font-family:Cinzel,serif;font-size:.78rem;letter-spacing:.15em;color:var(--gold);text-transform:uppercase;margin:0 0 1rem}
#bug-help-modal label{display:block;font-family:Cinzel,serif;font-size:.6rem;letter-spacing:.18em;color:var(--gold-dim);text-transform:uppercase;margin:0 0 .35rem}
#bug-help-modal input,#bug-help-modal textarea{width:100%;background:var(--dark-3,#1E1227);border:1px solid var(--border);color:var(--text);padding:.6rem .8rem;font-family:'Crimson Pro',Georgia,serif;font-size:.95rem;border-radius:4px;margin-bottom:.85rem;outline:none}
#bug-help-modal textarea{min-height:110px;resize:vertical}
#bug-help-modal .bug-actions{display:flex;gap:.6rem;justify-content:flex-end;margin-top:.25rem}
#bug-help-modal .bug-err{color:#CF4A4A;font-size:.82rem;font-style:italic;display:none;margin:0 0 .6rem}
#bug-help-send{background:linear-gradient(135deg,var(--gold),var(--gold-dim,#8A7235));color:var(--dark);border:1px solid var(--border-strong);border-radius:4px;padding:.4rem .9rem;font-family:Cinzel,serif;font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;cursor:pointer;font-weight:600}
#bug-help-cancel{background:transparent;color:var(--text-dim);border:1px solid var(--border);border-radius:4px;padding:.4rem .9rem;font-family:Cinzel,serif;font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;cursor:pointer}
`;

  window.initBugHelp = function initBugHelp(me) {
    if (!me || !me.authenticated || !me.bug_reports) {
      const btn = document.getElementById('bug-help-btn');
      if (btn) btn.remove();
      return;
    }
    if (document.getElementById('bug-help-btn')) return;

    if (!document.getElementById('bug-help-style')) {
      const st = document.createElement('style');
      st.id = 'bug-help-style';
      st.textContent = STYLE;
      document.head.appendChild(st);
    }

    const host = document.querySelector('.topbar-user');
    const badge = host && host.querySelector('.user-badge');
    if (!host || !badge) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'bug-help-btn';
    btn.setAttribute('aria-label', 'Report a bug');
    btn.textContent = '?';
    host.insertBefore(btn, badge);

    const overlay = document.createElement('div');
    overlay.id = 'bug-help-overlay';
    overlay.innerHTML =
      '<div id="bug-help-modal">' +
        '<h2>Report a bug</h2>' +
        '<div class="bug-err" id="bug-help-err"></div>' +
        '<label for="bug-help-name">Name</label>' +
        '<input id="bug-help-name" maxlength="80" autocomplete="name">' +
        '<label for="bug-help-email">Email</label>' +
        '<input id="bug-help-email" type="email" maxlength="120" autocomplete="email">' +
        '<label for="bug-help-issue">Issue</label>' +
        '<textarea id="bug-help-issue" maxlength="4000" placeholder="What happened?"></textarea>' +
        '<div class="bug-actions">' +
          '<button type="button" id="bug-help-cancel">Cancel</button>' +
          '<button type="button" id="bug-help-send">Send</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    const nameEl = document.getElementById('bug-help-name');
    const emailEl = document.getElementById('bug-help-email');
    const issueEl = document.getElementById('bug-help-issue');
    const errEl = document.getElementById('bug-help-err');
    if (me.username) nameEl.value = me.username;
    if (me.email) emailEl.value = me.email;

    function close() {
      overlay.classList.remove('show');
      errEl.style.display = 'none';
      issueEl.value = '';
    }
    btn.addEventListener('click', () => overlay.classList.add('show'));
    document.getElementById('bug-help-cancel').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    document.getElementById('bug-help-send').addEventListener('click', async () => {
      errEl.style.display = 'none';
      const send = document.getElementById('bug-help-send');
      send.disabled = true;
      try {
        const r = await fetch('/api/bugs', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            name: nameEl.value,
            email: emailEl.value,
            issue: issueEl.value,
            page: location.pathname,
          }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) {
          errEl.textContent = d.error || 'Could not send';
          errEl.style.display = 'block';
          send.disabled = false;
          return;
        }
        close();
        send.disabled = false;
        if (typeof toast === 'function') toast('Report sent. Thank you.', 'success');
      } catch (e) {
        errEl.textContent = 'Could not send';
        errEl.style.display = 'block';
        send.disabled = false;
      }
    });
  };
})();
