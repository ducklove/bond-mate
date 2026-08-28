/* 의존성 없는 SVG 차트 엔진.
 *
 * 외부 차트 라이브러리를 쓰지 않는 이유: GitHub Pages 정적 배포에 CDN 의존을
 * 더하면 첫 렌더가 네트워크에 묶이고, 이 서비스가 필요한 그림은 선·막대·곡선
 * 세 가지뿐이다. 직접 그리면 200줄 남짓이고 테마 색도 CSS 변수로 그대로 받는다.
 *
 * 제공하는 차트
 *   BMChart.line(box, opts)   시계열 (히스토리) — 다계열·크로스헤어·툴팁
 *   BMChart.curve(box, opts)  수익률 곡선 — x축이 만기(등간격 서수)
 *   BMChart.bars(box, opts)   국가·등급 비교 막대
 *
 * 공통 opts: {series|items, yFormat, height, yZero}
 * 모든 차트는 컨테이너 폭에 맞춰 viewBox 를 잡으므로 CSS 로 크기를 준다.
 */

'use strict';

const BMChart = (function () {
  const NS = 'http://www.w3.org/2000/svg';
  const PAD = { top: 12, right: 12, bottom: 22, left: 44 };

  function el(name, attrs) {
    const node = document.createElementNS(NS, name);
    for (const key in attrs) {
      if (attrs[key] != null) node.setAttribute(key, attrs[key]);
    }
    return node;
  }

  function clear(box) {
    box.innerHTML = '';
    const tip = document.createElement('div');
    tip.className = 'chart-tip';
    box.appendChild(tip);
    return tip;
  }

  /** 값 범위에 여유를 주고 눈금 후보를 고른다. */
  function niceScale(min, max, ticks) {
    if (!isFinite(min) || !isFinite(max)) return { min: 0, max: 1, step: 1 };
    if (min === max) { min -= 0.5; max += 0.5; }
    const span = max - min;
    const rawStep = span / (ticks || 4);
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const normalized = rawStep / magnitude;
    const step = (normalized >= 5 ? 5 : normalized >= 2 ? 2 : 1) * magnitude;
    return { min: Math.floor(min / step) * step, max: Math.ceil(max / step) * step, step };
  }

  function axisY(svg, scale, plot, format) {
    for (let value = scale.min; value <= scale.max + scale.step / 2; value += scale.step) {
      const y = plot.y(value);
      svg.appendChild(el('line', {
        class: 'c-grid', x1: plot.left, x2: plot.left + plot.width, y1: y, y2: y,
      }));
      const label = el('text', {
        class: 'c-axis-text', x: plot.left - 6, y: y + 3.5, 'text-anchor': 'end',
      });
      label.textContent = format ? format(value) : value.toFixed(2);
      svg.appendChild(label);
    }
  }

  function makePlot(width, height) {
    return {
      left: PAD.left,
      top: PAD.top,
      width: Math.max(10, width - PAD.left - PAD.right),
      height: Math.max(10, height - PAD.top - PAD.bottom),
    };
  }

  const MIN_WIDTH = 240;

  function boxWidth(box) {
    return Math.max(MIN_WIDTH, box.clientWidth || box.parentElement?.clientWidth || 640);
  }

  /**
   * 아직 레이아웃이 잡히지 않은 상태(탭 전환 직후·임베드 첫 렌더)에서 그리면
   * 폭이 0 으로 잡혀 viewBox 가 최소값이 되고, CSS 가 그걸 늘리면서 글자만
   * 거대해진다. 그런 경우 다음 프레임에 한 번 더 그린다.
   */
  function drawWhenSized(box, render) {
    render();
    if (box.clientWidth > MIN_WIDTH) return;
    requestAnimationFrame(() => {
      if (box.isConnected && box.clientWidth > MIN_WIDTH) render();
    });
  }

  /** 축 라벨 폭 어림(font-size 10.5). 한글은 전각이라 라틴 문자의 약 1.5배. */
  function estimateTextWidth(text) {
    let width = 0;
    for (const char of String(text)) {
      width += /[ㄱ-힝一-鿿]/.test(char) ? 10.5 : 6.2;
    }
    return width;
  }

  function seriesColor(series, index) {
    if (series.color) return series.color;
    const palette = ['--chart-ink', '--up', '--down', '--warn'];
    return cssVar(palette[index % palette.length], '#2563eb');
  }

  /* ── 시계열 ─────────────────────────────────────────────────────────── */
  function line(box, opts) {
    const tip = clear(box);
    const height = opts.height || 240;
    const width = boxWidth(box);
    const plot = makePlot(width, height);

    const visible = (opts.series || []).filter((s) => s.points && s.points.length && !s.hidden);
    if (!visible.length) {
      box.insertAdjacentHTML('beforeend', '<div class="empty">표시할 히스토리가 없습니다.</div>');
      return;
    }

    // x 는 날짜(ms), y 는 값. 여러 계열이 서로 다른 날짜를 가질 수 있어 합집합으로 잡는다.
    let tMin = Infinity, tMax = -Infinity, vMin = Infinity, vMax = -Infinity;
    visible.forEach((s) => {
      s._t = s.points.map((p) => Date.parse(p[0]));
      s.points.forEach((p, i) => {
        const t = s._t[i];
        if (t < tMin) tMin = t;
        if (t > tMax) tMax = t;
        if (p[1] < vMin) vMin = p[1];
        if (p[1] > vMax) vMax = p[1];
      });
    });
    if (opts.yZero) vMin = Math.min(0, vMin);
    const scale = niceScale(vMin, vMax, 4);
    const span = Math.max(1, tMax - tMin);

    plot.x = (t) => plot.left + ((t - tMin) / span) * plot.width;
    plot.y = (v) => plot.top + plot.height - ((v - scale.min) / (scale.max - scale.min)) * plot.height;

    const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img' });
    if (opts.label) svg.appendChild(Object.assign(el('title'), { textContent: opts.label }));
    axisY(svg, scale, plot, opts.yFormat);

    // x축 라벨 — 양 끝과 가운데만 (좁은 화면에서 겹치지 않게)
    [tMin, tMin + span / 2, tMax].forEach((t, i) => {
      const text = el('text', {
        class: 'c-axis-text',
        x: plot.x(t),
        y: plot.top + plot.height + 14,
        'text-anchor': i === 0 ? 'start' : i === 2 ? 'end' : 'middle',
      });
      const d = new Date(t);
      text.textContent = d.getFullYear() + '.' + String(d.getMonth() + 1).padStart(2, '0');
      svg.appendChild(text);
    });

    visible.forEach((s, index) => {
      const color = seriesColor(s, index);
      const path = s.points.map((p, i) => (i ? 'L' : 'M') + plot.x(s._t[i]).toFixed(1) + ' ' + plot.y(p[1]).toFixed(1)).join('');
      if (visible.length === 1 && opts.area !== false) {
        const base = plot.top + plot.height;
        svg.appendChild(el('path', {
          class: 'c-area', fill: color,
          d: path + `L${plot.x(s._t[s._t.length - 1]).toFixed(1)} ${base}L${plot.x(s._t[0]).toFixed(1)} ${base}Z`,
        }));
      }
      svg.appendChild(el('path', { class: 'c-line', stroke: color, d: path }));
      s._color = color;
    });

    const cross = el('line', { class: 'c-hover-line', y1: plot.top, y2: plot.top + plot.height, opacity: 0 });
    svg.appendChild(cross);
    const dots = visible.map((s) => {
      const dot = el('circle', { class: 'c-dot', r: 3.5, fill: s._color, opacity: 0 });
      svg.appendChild(dot);
      return dot;
    });

    const overlay = el('rect', {
      x: plot.left, y: plot.top, width: plot.width, height: plot.height, fill: 'transparent',
    });
    svg.appendChild(overlay);
    box.appendChild(svg);

    function nearest(series, t) {
      let lo = 0, hi = series._t.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (series._t[mid] < t) lo = mid + 1; else hi = mid;
      }
      if (lo > 0 && Math.abs(series._t[lo - 1] - t) < Math.abs(series._t[lo] - t)) lo -= 1;
      return lo;
    }

    function move(event) {
      const rect = svg.getBoundingClientRect();
      const px = ((event.touches ? event.touches[0].clientX : event.clientX) - rect.left) * (width / rect.width);
      const t = tMin + ((px - plot.left) / plot.width) * span;
      const rows = [];
      let anchorDate = '';
      visible.forEach((s, i) => {
        const index = nearest(s, t);
        const point = s.points[index];
        if (!point) { dots[i].setAttribute('opacity', 0); return; }
        anchorDate = point[0];
        dots[i].setAttribute('cx', plot.x(s._t[index]));
        dots[i].setAttribute('cy', plot.y(point[1]));
        dots[i].setAttribute('opacity', 1);
        rows.push(
          '<div class="tip-row"><span class="tip-swatch" style="background:' + s._color + '"></span>' +
          escapeHtml(s.label || s.key) + ' ' +
          (opts.yFormat ? opts.yFormat(point[1]) : point[1]) + '</div>'
        );
      });
      const anchorX = plot.x(Date.parse(anchorDate));
      cross.setAttribute('x1', anchorX);
      cross.setAttribute('x2', anchorX);
      cross.setAttribute('opacity', 1);
      tip.innerHTML = '<span class="tip-date">' + fmtDate(anchorDate) + '</span>' + rows.join('');
      tip.classList.add('on');
      tip.style.left = (anchorX / width) * 100 + '%';
      tip.style.top = (plot.top + 4) + 'px';
    }

    function leave() {
      cross.setAttribute('opacity', 0);
      dots.forEach((d) => d.setAttribute('opacity', 0));
      tip.classList.remove('on');
    }

    overlay.addEventListener('mousemove', move);
    overlay.addEventListener('mouseleave', leave);
    overlay.addEventListener('touchmove', move, { passive: true });
    overlay.addEventListener('touchend', leave);
  }

  /* ── 수익률 곡선 ────────────────────────────────────────────────────── */
  // x 를 만기 실수값에 비례시키면 단기 구간이 뭉개진다(3M~2Y 가 30Y 옆에서 한 점).
  // 그래서 표시된 만기들을 **등간격 서수**로 놓는다 — 커브 UI 의 통상적인 방식이고
  // 기준금리(-1)·익일물(0) 같은 비만기 항목도 자연스럽게 자리를 얻는다.
  function curve(box, opts) {
    const tip = clear(box);
    const height = opts.height || 260;
    const width = boxWidth(box);
    const plot = makePlot(width, height);

    const visible = (opts.series || []).filter((s) => s.points && s.points.length && !s.hidden);
    if (!visible.length) {
      box.insertAdjacentHTML('beforeend', '<div class="empty">표시할 곡선이 없습니다.</div>');
      return;
    }

    const axis = [];
    visible.forEach((s) => s.points.forEach((p) => {
      if (!axis.some((a) => a.maturity === p[0])) axis.push({ maturity: p[0], label: p[2] });
    }));
    axis.sort((a, b) => a.maturity - b.maturity);
    const slotOf = new Map(axis.map((a, i) => [a.maturity, i]));

    let vMin = Infinity, vMax = -Infinity;
    visible.forEach((s) => s.points.forEach((p) => {
      if (p[1] < vMin) vMin = p[1];
      if (p[1] > vMax) vMax = p[1];
    }));
    const scale = niceScale(vMin, vMax, 4);
    const step = plot.width / Math.max(1, axis.length - 1);

    plot.x = (maturity) => plot.left + slotOf.get(maturity) * step;
    plot.y = (v) => plot.top + plot.height - ((v - scale.min) / (scale.max - scale.min)) * plot.height;

    const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img' });
    axisY(svg, scale, plot, opts.yFormat);

    // 만기 라벨 — 라벨 폭이 제각각이라(‘기준금리’ 4자 vs ‘2년’ 2자) 중심 간격만
    // 보면 넓은 라벨이 옆 라벨을 파고든다. 글자 폭을 어림해 **차지하는 구간**으로
    // 겹침을 판정한다. 마지막 만기는 기준점이라 먼저 자리를 잡는다.
    const placed = [];
    const order = [axis.length - 1, ...axis.map((_, i) => i).slice(0, -1)];
    order.forEach((index) => {
      const at = axis[index];
      const text = at.label || maturityLabel(at.maturity);
      const x = plot.x(at.maturity);
      const half = estimateTextWidth(text) / 2 + 4;   // 좌우 4px 여백
      // 양 끝 라벨을 가운데 정렬하면 플롯 밖으로 삐져나가 y축 눈금(왼쪽)이나
      // 컨테이너 경계(오른쪽)와 부딪힌다. 끝에서는 안쪽으로 붙인다.
      const overflowsLeft = x - half < plot.left;
      const overflowsRight = x + half > plot.left + plot.width;
      const anchor = overflowsLeft ? 'start' : overflowsRight ? 'end' : 'middle';
      const span = anchor === 'start' ? { left: x, right: x + half * 2 }
        : anchor === 'end' ? { left: x - half * 2, right: x }
        : { left: x - half, right: x + half };
      if (placed.some((used) => span.left < used.right && span.right > used.left)) return;
      placed.push(span);
      const node = el('text', {
        class: 'c-axis-text', x, y: plot.top + plot.height + 14, 'text-anchor': anchor,
      });
      node.textContent = text;
      svg.appendChild(node);
    });

    visible.forEach((s, index) => {
      const color = seriesColor(s, index);
      s._color = color;
      const sorted = s.points.slice().sort((a, b) => a[0] - b[0]);
      const path = sorted.map((p, i) => (i ? 'L' : 'M') + plot.x(p[0]).toFixed(1) + ' ' + plot.y(p[1]).toFixed(1)).join('');
      svg.appendChild(el('path', { class: 'c-line', stroke: color, d: path }));
      sorted.forEach((p) => {
        const dot = el('circle', { class: 'c-dot', r: 3, fill: color, cx: plot.x(p[0]), cy: plot.y(p[1]) });
        const title = el('title');
        title.textContent = (s.label || '') + ' ' + (p[2] || maturityLabel(p[0])) + ' ' +
          (opts.yFormat ? opts.yFormat(p[1]) : p[1]);
        dot.appendChild(title);
        svg.appendChild(dot);
      });
    });

    const cross = el('line', { class: 'c-hover-line', y1: plot.top, y2: plot.top + plot.height, opacity: 0 });
    svg.appendChild(cross);
    const overlay = el('rect', {
      x: plot.left, y: plot.top, width: plot.width, height: plot.height, fill: 'transparent',
    });
    svg.appendChild(overlay);
    box.appendChild(svg);

    overlay.addEventListener('mousemove', (event) => {
      const rect = svg.getBoundingClientRect();
      const px = (event.clientX - rect.left) * (width / rect.width);
      const slot = Math.max(0, Math.min(axis.length - 1, Math.round((px - plot.left) / step)));
      const at = axis[slot];
      const rows = visible.map((s) => {
        const point = s.points.find((p) => p[0] === at.maturity);
        if (!point) return '';
        return '<div class="tip-row"><span class="tip-swatch" style="background:' + s._color + '"></span>' +
          escapeHtml(s.label || s.key) + ' ' + (opts.yFormat ? opts.yFormat(point[1]) : point[1]) + '</div>';
      }).filter(Boolean);
      cross.setAttribute('x1', plot.x(at.maturity));
      cross.setAttribute('x2', plot.x(at.maturity));
      cross.setAttribute('opacity', 1);
      tip.innerHTML = '<span class="tip-date">만기 ' + escapeHtml(at.label || maturityLabel(at.maturity)) + '</span>' + rows.join('');
      tip.classList.add('on');
      tip.style.left = (plot.x(at.maturity) / width) * 100 + '%';
      tip.style.top = (plot.top + 4) + 'px';
    });
    overlay.addEventListener('mouseleave', () => {
      cross.setAttribute('opacity', 0);
      tip.classList.remove('on');
    });
  }

  /* ── 비교 막대 ──────────────────────────────────────────────────────── */
  function bars(box, opts) {
    clear(box);
    const items = (opts.items || []).filter((i) => i.value != null && isFinite(i.value));
    if (!items.length) {
      box.insertAdjacentHTML('beforeend', '<div class="empty">표시할 값이 없습니다.</div>');
      return;
    }

    const rowHeight = opts.rowHeight || 22;
    const width = boxWidth(box);
    const height = items.length * rowHeight + 12;
    const labelWidth = opts.labelWidth || 74;
    const plotLeft = labelWidth;
    const plotWidth = Math.max(20, width - labelWidth - 52);

    const max = Math.max(...items.map((i) => i.value));
    const min = Math.min(0, ...items.map((i) => i.value));
    const span = Math.max(1e-6, max - min);
    const x = (v) => plotLeft + ((v - min) / span) * plotWidth;

    const svg = el('svg', { viewBox: `0 0 ${width} ${height}` });
    items.forEach((item, index) => {
      const y = index * rowHeight + 6;
      const label = el('text', { class: 'c-axis-text', x: labelWidth - 8, y: y + rowHeight / 2 + 1, 'text-anchor': 'end' });
      label.textContent = item.label;
      svg.appendChild(label);

      const zero = x(Math.max(min, 0));
      const bar = x(item.value);
      svg.appendChild(el('rect', {
        class: 'c-bar',
        x: Math.min(zero, bar),
        y: y + 3,
        width: Math.max(1, Math.abs(bar - zero)),
        height: rowHeight - 9,
        fill: item.color || cssVar('--chart-ink', '#2563eb'),
        opacity: item.dim ? 0.45 : 0.85,
      }));

      const value = el('text', { class: 'c-axis-text', x: bar + 6, y: y + rowHeight / 2 + 1 });
      value.textContent = opts.yFormat ? opts.yFormat(item.value) : item.value;
      svg.appendChild(value);
    });
    box.appendChild(svg);
  }

  // 모든 차트는 폭이 잡힌 뒤에 확정 렌더된다.
  return {
    line: (box, opts) => drawWhenSized(box, () => line(box, opts)),
    curve: (box, opts) => drawWhenSized(box, () => curve(box, opts)),
    bars: (box, opts) => drawWhenSized(box, () => bars(box, opts)),
  };
})();
