/**
 * script.js — клиентская логика главной страницы.
 * Загружает список ЧС, детали, планы эвакуации и видео через REST API.
 * Рисует интерактивные зоны и полилинию маршрута поверх изображения плана.
 */

(function () {
  'use strict';

  const apiBase = '';

  /** Показать Bootstrap-alert вверху страницы */
  function showAlert(message, type = 'danger') {
    const root = document.getElementById('alert-root');
    if (!root) return;
    root.innerHTML =
      '<div class="alert alert-' +
      type +
      ' alert-dismissible fade show" role="alert">' +
      escapeHtml(message) +
      '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>';
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  async function fetchJson(url) {
    const res = await fetch(apiBase + url, { credentials: 'same-origin' });
    if (!res.ok) {
      const err = await res.json().catch(function () {
        return {};
      });
      throw new Error(err.detail || res.statusText || 'Ошибка запроса');
    }
    return res.json();
  }

  let emergenciesCache = [];
  let selectedEmergencyId = null;
  let plansCache = [];
  let activePlanIndex = 0;

  /** Загрузка и отрисовка списка ЧС */
  async function loadEmergencies() {
    const listEl = document.getElementById('emergency-list');
    try {
      emergenciesCache = await fetchJson('/api/emergencies');
      listEl.innerHTML = '';
      if (!emergenciesCache.length) {
        listEl.innerHTML = '<div class="p-3 text-body-secondary small">Нет данных. Добавьте ЧС в админ-панели.</div>';
        return;
      }
      emergenciesCache.forEach(function (em) {
        const a = document.createElement('button');
        a.type = 'button';
        a.className = 'list-group-item list-group-item-action';
        a.dataset.id = String(em.id);
        a.innerHTML =
          '<div class="fw-semibold">' +
          escapeHtml(em.title) +
          '</div><div class="small text-secondary">' +
          escapeHtml(em.short_description || '') +
          '</div>';
        a.addEventListener('click', function () {
          selectEmergency(em.id);
        });
        listEl.appendChild(a);
      });
    } catch (e) {
      listEl.innerHTML = '<div class="p-3 text-danger small">Не удалось загрузить список: ' + escapeHtml(e.message) + '</div>';
      showAlert(e.message);
    }
  }

  function setActiveListItem(id) {
    document.querySelectorAll('#emergency-list .list-group-item').forEach(function (el) {
      el.classList.toggle('active', el.dataset.id === String(id));
    });
  }

  /** Выбор ЧС: подгрузка деталей, планов, видео */
  async function selectEmergency(id) {
    selectedEmergencyId = id;
    setActiveListItem(id);
    document.getElementById('emergency-empty').classList.add('d-none');
    document.getElementById('emergency-detail').classList.remove('d-none');

    try {
      const detail = await fetchJson('/api/emergencies/' + id);
      document.getElementById('detail-title').textContent = detail.title;
      document.getElementById('detail-short').textContent = detail.short_description || '';
      document.getElementById('detail-reco').innerHTML = detail.recommendations || '<p class="text-secondary small mb-0">Рекомендации не заданы.</p>';

      plansCache = await fetchJson('/api/evacuation-plans?emergency_id=' + id);
      activePlanIndex = 0;
      renderPlanTabs();
      renderActivePlan();

      const videos = await fetchJson('/api/video-instructions?emergency_id=' + id);
      renderVideos(videos);
    } catch (e) {
      showAlert(e.message);
    }
  }

  function renderPlanTabs() {
    const tabs = document.getElementById('plan-tabs');
    const plansCard = document.getElementById('plans');
    tabs.innerHTML = '';
    if (!plansCache.length) {
      plansCard.querySelector('.card-body').innerHTML =
        '<p class="text-secondary small mb-0">Для этой ситуации пока нет загруженных планов эвакуации.</p>';
      return;
    }
    // Восстановить разметку card-body если ранее очищали
    const cardBody = plansCard.querySelector('.card-body');
    if (!cardBody.querySelector('.map-shell')) {
      cardBody.innerHTML =
        '<p id="plan-desc" class="small text-secondary mb-2"></p>' +
        '<div class="map-shell position-relative mx-auto">' +
        '<img id="plan-image" class="plan-image" alt="План этажа" src="">' +
        '<svg id="plan-overlay" class="plan-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"></svg>' +
        '<div id="plan-zones" class="plan-zones"></div></div>' +
        '<p id="zone-hint" class="mt-3 small text-primary fw-medium mb-0"></p>';
    }
    plansCache.forEach(function (plan, idx) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-outline-primary' + (idx === activePlanIndex ? ' active' : '');
      btn.textContent = plan.title || 'План ' + (idx + 1);
      btn.addEventListener('click', function () {
        activePlanIndex = idx;
        renderPlanTabs();
        renderActivePlan();
      });
      tabs.appendChild(btn);
    });
  }

  /** Отрисовка текущего плана: изображение, маршрут SVG, зоны */
  function renderActivePlan() {
    const hintEl = document.getElementById('zone-hint');
    if (hintEl) hintEl.textContent = '';
    if (!plansCache.length) return;

    const plan = plansCache[activePlanIndex];
    const descEl = document.getElementById('plan-desc');
    if (descEl) descEl.textContent = plan.description || '';

    const img = document.getElementById('plan-image');
    const svg = document.getElementById('plan-overlay');
    const zonesRoot = document.getElementById('plan-zones');
    img.src = plan.image_url;
    img.alt = plan.title || 'План эвакуации';

    zonesRoot.innerHTML = '';
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const hs = plan.hotspots || {};
    const zones = Array.isArray(hs.zones) ? hs.zones : [];
    const route = hs.route && hs.route.points ? hs.route : null;

    zones.forEach(function (z) {
      const div = document.createElement('button');
      div.type = 'button';
      div.className = 'plan-zone';
      div.style.left = z.x + '%';
      div.style.top = z.y + '%';
      div.style.width = z.w + '%';
      div.style.height = z.h + '%';
      div.setAttribute('aria-label', z.label || 'Зона');
      div.title = z.label || '';
      const lab = document.createElement('span');
      lab.className = 'zone-label';
      lab.textContent = z.label || '';
      div.appendChild(lab);
      div.addEventListener('click', function () {
        if (hintEl) {
          hintEl.textContent = (z.label ? z.label + ': ' : '') + (z.hint || 'Нет текстовой подсказки для зоны.');
        }
      });
      zonesRoot.appendChild(div);
    });

    if (route && route.points.length > 1) {
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      const pts = route.points.map(function (p) {
        return p[0] + ',' + p[1];
      });
      poly.setAttribute('points', pts.join(' '));
      poly.setAttribute('class', 'route-line');
      svg.appendChild(poly);
      route.points.forEach(function (p) {
        const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        c.setAttribute('cx', p[0]);
        c.setAttribute('cy', p[1]);
        c.setAttribute('r', 1.1);
        c.setAttribute('class', 'route-point');
        svg.appendChild(c);
      });
    }
  }

  function renderVideos(videos) {
    const root = document.getElementById('video-list');
    root.innerHTML = '';
    if (!videos.length) {
      root.innerHTML = '<p class="text-body-secondary small mb-0">Видео для этой ситуации не добавлены.</p>';
      return;
    }
    videos.forEach(function (v) {
      const col = document.createElement('div');
      col.className = 'col-12';
      const card = document.createElement('div');
      card.className = 'video-card-inner p-3';
      const body = document.createElement('div');
      body.className = 'card-body p-0';
      if (v.author_name) {
        const auth = document.createElement('div');
        auth.className = 'video-author-badge';
        auth.textContent = 'Материал: ' + v.author_name;
        body.appendChild(auth);
      }
      const title = document.createElement('h3');
      title.className = 'h6 fw-semibold mb-2';
      title.textContent = v.title;
      const desc = document.createElement('p');
      desc.className = 'small text-body-secondary mb-3';
      desc.textContent = v.description || '';
      const ratio = document.createElement('div');
      ratio.className = 'ratio-video';

      /* Приоритет: Rutube → YouTube (архив) → локальный файл */
      if (v.rutube_id) {
        const iframe = document.createElement('iframe');
        iframe.loading = 'lazy';
        iframe.title = v.title;
        iframe.setAttribute(
          'allow',
          'clipboard-write; autoplay; encrypted-media; gyroscope; picture-in-picture; fullscreen'
        );
        iframe.setAttribute('allowfullscreen', '');
        iframe.src = 'https://rutube.ru/play/embed/' + encodeURIComponent(v.rutube_id);
        ratio.appendChild(iframe);
      } else if (v.youtube_id) {
        const iframe = document.createElement('iframe');
        iframe.loading = 'lazy';
        iframe.title = v.title;
        iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture';
        iframe.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(v.youtube_id);
        ratio.appendChild(iframe);
      } else if (v.local_url) {
        const video = document.createElement('video');
        video.controls = true;
        video.src = v.local_url;
        ratio.appendChild(video);
      } else {
        ratio.innerHTML = '<p class="text-white small p-2 mb-0">Нет источника видео</p>';
      }

      body.appendChild(title);
      body.appendChild(desc);
      body.appendChild(ratio);
      card.appendChild(body);
      col.appendChild(card);
      root.appendChild(col);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    loadEmergencies();
  });
})();
