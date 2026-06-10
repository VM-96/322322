/**
 * admin.js — формы входа и CRUD в админ-панели.
 * Использует cookie-сессию (credentials: 'include' для fetch).
 */

(function () {
  'use strict';

  const apiBase = '';

  function alertBox(message, type) {
    const root = document.getElementById('admin-alerts');
    if (!root) return;
    const div = document.createElement('div');
    div.className = 'alert alert-' + (type || 'info') + ' alert-dismissible fade show';
    div.innerHTML =
      '<span>' +
      escapeHtml(message) +
      '</span><button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
    root.appendChild(div);
    setTimeout(function () {
      try {
        div.remove();
      } catch (e) {}
    }, 6000);
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  async function fetchJson(url, options) {
    const opts = options || {};
    opts.credentials = 'same-origin';
    if (!opts.headers) opts.headers = {};
    if (opts.body && !(opts.body instanceof FormData) && !opts.headers['Content-Type']) {
      opts.headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(apiBase + url, opts);
    const data = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) {
      const msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
      throw new Error(msg || res.statusText);
    }
    return data;
  }

  function showLogin() {
    document.getElementById('login-section').classList.remove('d-none');
    document.getElementById('admin-panel').classList.add('d-none');
  }

  function showPanel(username) {
    document.getElementById('login-section').classList.add('d-none');
    document.getElementById('admin-panel').classList.remove('d-none');
    document.getElementById('admin-user-label').textContent = username || '';
  }

  async function checkMe() {
    try {
      const me = await fetchJson('/api/admin/me');
      if (me.authenticated) {
        showPanel(me.username);
        await refreshAll();
        return true;
      }
    } catch (e) {}
    showLogin();
    return false;
  }

  async function refreshAll() {
    const emergencies = await fetchJson('/api/emergencies');
    fillEmergencySelects(emergencies);
    await renderEmergencyAdminList(emergencies);
    await renderPlansAdmin(emergencies);
    await renderVideosAdmin(emergencies);
  }

  function fillEmergencySelects(list) {
    ['plan-em-select', 'video-em-select'].forEach(function (id) {
      const sel = document.getElementById(id);
      if (!sel) return;
      sel.innerHTML = '';
      list.forEach(function (em) {
        const o = document.createElement('option');
        o.value = String(em.id);
        o.textContent = em.title + ' (' + em.code + ')';
        sel.appendChild(o);
      });
    });
  }

  async function renderEmergencyAdminList(list) {
    const root = document.getElementById('emergency-admin-list');
    root.innerHTML = '';
    /* Полная карточка (включая recommendations) доступна только в GET /api/emergencies/{id} */
    const fullList = await Promise.all(
      list.map(function (em) {
        return fetchJson('/api/emergencies/' + em.id);
      })
    );
    for (const em of fullList) {
      const wrap = document.createElement('div');
      wrap.className = 'border rounded p-2 small';
      wrap.innerHTML =
        '<div class="fw-semibold mb-2">' +
        escapeHtml(em.title) +
        ' <span class="text-muted">(' +
        escapeHtml(em.code) +
        ')</span></div>' +
        '<div class="row g-1">' +
        '<div class="col-12"><input type="text" class="form-control form-control-sm em-title" data-id="' +
        em.id +
        '" value="' +
        escapeAttr(em.title) +
        '"></div>' +
        '<div class="col-12"><input type="text" class="form-control form-control-sm em-short" placeholder="Кратко" data-id="' +
        em.id +
        '" value="' +
        escapeAttr(em.short_description || '') +
        '"></div>' +
        '<div class="col-12"><textarea class="form-control form-control-sm em-reco" rows="2" data-id="' +
        em.id +
        '">' +
        escapeHtml(em.recommendations || '') +
        '</textarea></div>' +
        '<div class="col-6"><input type="number" class="form-control form-control-sm em-sort" data-id="' +
        em.id +
        '" value="' +
        em.sort_order +
        '"></div>' +
        '<div class="col-6 text-end">' +
        '<button type="button" class="btn btn-sm btn-primary em-save" data-id="' +
        em.id +
        '">Сохранить</button> ' +
        '<button type="button" class="btn btn-sm btn-outline-danger em-del" data-id="' +
        em.id +
        '">Удалить</button>' +
        '</div></div>';
      root.appendChild(wrap);
    }

    root.querySelectorAll('.em-save').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const id = btn.dataset.id;
        const fd = new FormData();
        fd.append('title', root.querySelector('.em-title[data-id="' + id + '"]').value);
        fd.append('short_description', root.querySelector('.em-short[data-id="' + id + '"]').value);
        fd.append('recommendations', root.querySelector('.em-reco[data-id="' + id + '"]').value);
        fd.append('sort_order', root.querySelector('.em-sort[data-id="' + id + '"]').value);
        try {
          await fetchJson('/api/admin/emergencies/' + id, { method: 'PUT', body: fd });
          alertBox('ЧС сохранена', 'success');
          await refreshAll();
        } catch (e) {
          alertBox(e.message, 'danger');
        }
      });
    });
    root.querySelectorAll('.em-del').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        if (!confirm('Удалить ЧС и все связанные планы/видео?')) return;
        try {
          await fetchJson('/api/admin/emergencies/' + btn.dataset.id, { method: 'DELETE' });
          alertBox('Удалено', 'success');
          await refreshAll();
        } catch (e) {
          alertBox(e.message, 'danger');
        }
      });
    });
  }

  function escapeAttr(s) {
    return String(s).replace(/"/g, '&quot;');
  }

  async function renderPlansAdmin(emergencies) {
    const root = document.getElementById('plans-admin-list');
    root.innerHTML = '';
    for (const em of emergencies) {
      const plans = await fetchJson('/api/evacuation-plans?emergency_id=' + em.id);
      if (!plans.length) continue;
      const block = document.createElement('div');
      block.className = 'border rounded p-2';
      block.innerHTML = '<div class="fw-semibold small mb-2">' + escapeHtml(em.title) + '</div>';
      const list = document.createElement('div');
      list.className = 'vstack gap-2';
      plans.forEach(function (p) {
        const row = document.createElement('div');
        row.className = 'small border rounded p-2 bg-light';
        row.innerHTML =
          '<div class="mb-1 fw-medium">' +
          escapeHtml(p.title) +
          ' <span class="text-muted">#' +
          p.id +
          '</span></div>' +
          '<div class="row g-1">' +
          '<div class="col-md-6"><input type="text" class="form-control form-control-sm pt-title" data-id="' +
          p.id +
          '" value="' +
          escapeAttr(p.title) +
          '"></div>' +
          '<div class="col-md-3"><input type="number" class="form-control form-control-sm pt-sort" data-id="' +
          p.id +
          '" value="' +
          p.sort_order +
          '"></div>' +
          '<div class="col-md-3 text-end">' +
          '<button type="button" class="btn btn-sm btn-outline-danger pt-del" data-id="' +
          p.id +
          '">Удалить</button>' +
          '</div>' +
          '<div class="col-12"><input type="text" class="form-control form-control-sm pt-desc" data-id="' +
          p.id +
          '" value="' +
          escapeAttr(p.description || '') +
          '"></div>' +
          '<div class="col-12"><textarea class="form-control form-control-sm font-monospace pt-json" rows="4" data-id="' +
          p.id +
          '">' +
          escapeHtml(JSON.stringify(p.hotspots || {}, null, 2)) +
          '</textarea></div>' +
          '<div class="col-12"><input type="file" class="form-control form-control-sm pt-file" data-id="' +
          p.id +
          '" accept="image/*"></div>' +
          '<div class="col-12"><button type="button" class="btn btn-sm btn-primary pt-save" data-id="' +
          p.id +
          '">Обновить план</button></div>' +
          '</div>';
        list.appendChild(row);
      });
      block.appendChild(list);
      root.appendChild(block);
    }

    root.querySelectorAll('.pt-save').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const id = btn.dataset.id;
        const fd = new FormData();
        fd.append('title', root.querySelector('.pt-title[data-id="' + id + '"]').value);
        fd.append('description', root.querySelector('.pt-desc[data-id="' + id + '"]').value);
        fd.append('sort_order', root.querySelector('.pt-sort[data-id="' + id + '"]').value);
        fd.append('hotspots_json', root.querySelector('.pt-json[data-id="' + id + '"]').value);
        const fileInp = root.querySelector('.pt-file[data-id="' + id + '"]');
        if (fileInp.files && fileInp.files[0]) fd.append('image', fileInp.files[0]);
        try {
          await fetchJson('/api/admin/evacuation-plans/' + id, { method: 'PUT', body: fd });
          alertBox('План обновлён', 'success');
          const emList = await fetchJson('/api/emergencies');
          await renderPlansAdmin(emList);
        } catch (e) {
          alertBox(e.message, 'danger');
        }
      });
    });
    root.querySelectorAll('.pt-del').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        if (!confirm('Удалить план?')) return;
        try {
          await fetchJson('/api/admin/evacuation-plans/' + btn.dataset.id, { method: 'DELETE' });
          alertBox('План удалён', 'success');
          const emList = await fetchJson('/api/emergencies');
          await renderPlansAdmin(emList);
        } catch (e) {
          alertBox(e.message, 'danger');
        }
      });
    });
  }

  async function renderVideosAdmin(emergencies) {
    const root = document.getElementById('videos-admin-list');
    root.innerHTML = '';
    for (const em of emergencies) {
      const vids = await fetchJson('/api/video-instructions?emergency_id=' + em.id);
      vids.forEach(function (v) {
        const row = document.createElement('div');
        row.className = 'border rounded p-2 small';
        row.innerHTML =
          '<div class="fw-semibold">' +
          escapeHtml(em.title) +
          ': ' +
          escapeHtml(v.title) +
          ' <span class="text-muted">#' +
          v.id +
          '</span></div>' +
          '<div class="row g-1 mt-1">' +
          '<div class="col-md-6"><input type="text" class="form-control form-control-sm vt-title" placeholder="Заголовок" data-id="' +
          v.id +
          '" value="' +
          escapeAttr(v.title) +
          '"></div>' +
          '<div class="col-md-3"><input type="text" class="form-control form-control-sm vt-author" placeholder="Автор / подразделение" data-id="' +
          v.id +
          '" value="' +
          escapeAttr(v.author_name || '') +
          '"></div>' +
          '<div class="col-md-2"><input type="number" class="form-control form-control-sm vt-sort" data-id="' +
          v.id +
          '" value="' +
          v.sort_order +
          '"></div>' +
          '<div class="col-md-1 text-end">' +
          '<button type="button" class="btn btn-sm btn-outline-danger vt-del" data-id="' +
          v.id +
          '">×</button>' +
          '</div>' +
          '<div class="col-12"><input type="text" class="form-control form-control-sm vt-desc" placeholder="Описание" data-id="' +
          v.id +
          '" value="' +
          escapeAttr(v.description || '') +
          '"></div>' +
          '<div class="col-md-6"><input type="text" class="form-control form-control-sm vt-ru" placeholder="Rutube ID" data-id="' +
          v.id +
          '" value="' +
          escapeAttr(v.rutube_id || '') +
          '"></div>' +
          '<div class="col-md-6"><input type="text" class="form-control form-control-sm vt-yt" placeholder="rutube id (опц.)" data-id="' +
          v.id +
          '" value="' +
          escapeAttr(v.rutube_id || '') +
          '"></div>' +
          '<div class="col-12"><input type="file" class="form-control form-control-sm vt-file" data-id="' +
          v.id +
          '" accept="video/*"></div>' +
          '<div class="col-12"><button type="button" class="btn btn-sm btn-primary vt-save" data-id="' +
          v.id +
          '">Сохранить</button></div>' +
          '</div>';
        root.appendChild(row);
      });
    }

    root.querySelectorAll('.vt-save').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const id = btn.dataset.id;
        const fd = new FormData();
        fd.append('title', root.querySelector('.vt-title[data-id="' + id + '"]').value);
        fd.append('description', root.querySelector('.vt-desc[data-id="' + id + '"]').value);
        fd.append('author_name', root.querySelector('.vt-author[data-id="' + id + '"]').value);
        fd.append('rutube_id', root.querySelector('.vt-ru[data-id="' + id + '"]').value);
        fd.append('rutube_id', root.querySelector('.vt-yt[data-id="' + id + '"]').value);
        fd.append('sort_order', root.querySelector('.vt-sort[data-id="' + id + '"]').value);
        const f = root.querySelector('.vt-file[data-id="' + id + '"]');
        if (f.files && f.files[0]) fd.append('video_file', f.files[0]);
        try {
          await fetchJson('/api/admin/video-instructions/' + id, { method: 'PUT', body: fd });
          alertBox('Видео обновлено', 'success');
          const emList = await fetchJson('/api/emergencies');
          await renderVideosAdmin(emList);
        } catch (e) {
          alertBox(e.message, 'danger');
        }
      });
    });
    root.querySelectorAll('.vt-del').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        if (!confirm('Удалить видео?')) return;
        try {
          await fetchJson('/api/admin/video-instructions/' + btn.dataset.id, { method: 'DELETE' });
          alertBox('Удалено', 'success');
          const emList = await fetchJson('/api/emergencies');
          await renderVideosAdmin(emList);
        } catch (e) {
          alertBox(e.message, 'danger');
        }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('login-form').addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      try {
        await fetchJson('/api/admin/login', {
          method: 'POST',
          body: JSON.stringify({
            username: fd.get('username'),
            password: fd.get('password'),
          }),
        });
        alertBox('Добро пожаловать', 'success');
        await checkMe();
      } catch (e) {
        alertBox(e.message, 'danger');
      }
    });

    document.getElementById('btn-logout').addEventListener('click', async function () {
      await fetchJson('/api/admin/logout', { method: 'POST' });
      showLogin();
    });

    document.getElementById('form-em-create').addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      try {
        await fetchJson('/api/admin/emergencies', { method: 'POST', body: fd });
        ev.target.reset();
        alertBox('ЧС добавлена', 'success');
        await refreshAll();
      } catch (e) {
        alertBox(e.message, 'danger');
      }
    });

    document.getElementById('form-plan-create').addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      try {
        await fetchJson('/api/admin/evacuation-plans', { method: 'POST', body: fd });
        ev.target.querySelector('input[name=image]').value = '';
        alertBox('План загружен', 'success');
        await refreshAll();
      } catch (e) {
        alertBox(e.message, 'danger');
      }
    });

    document.getElementById('form-video-create').addEventListener('submit', async function (ev) {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      try {
        await fetchJson('/api/admin/video-instructions', { method: 'POST', body: fd });
        ev.target.reset();
        alertBox('Видео добавлено', 'success');
        await refreshAll();
      } catch (e) {
        alertBox(e.message, 'danger');
      }
    });

    checkMe();
  });
})();
