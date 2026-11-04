/* Optional, local enhancement of an already complete static illustration. */
(() => {
  'use strict';
  const root = document.getElementById('orbital');
  if (!root || !window.PointerEvent || !window.matchMedia || !window.requestAnimationFrame) return;
  const art = root.querySelector('.orbital-art');
  const svg = art.querySelector('svg');
  const field = root.querySelector('#orbital-field');
  const still = root.querySelector('#orbital-static-helix');
  const handle = root.querySelector('.helix-control');
  const controls = root.querySelector('.orbital-controls');
  const left = root.querySelector('#orbital-left');
  const right = root.querySelector('#orbital-right');
  const play = root.querySelector('#orbital-play');
  const mode = root.querySelector('#orbital-mode');
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let drawing, paths, frame = 0, phase = 0, paintedPhase = -1;
  let x = 0, y = 0, targetX = 0, targetY = 0, drag = null;
  let paused = false, failed = false, enabled = false;
  let spinning = false, lastTick = null;

  function release() {
    const previous = drag;
    drag = null;
    root.classList.remove('is-dragging');
    if (previous && handle.hasPointerCapture(previous.id)) handle.releasePointerCapture(previous.id);
  }

  function staticArtwork() {
    enabled = false;
    setPlaying(false);
    cancelAnimationFrame(frame);
    frame = 0;
    release();
    field.removeAttribute('transform');
    still.removeAttribute('visibility');
    if (drawing) drawing.setAttribute('visibility', 'hidden');
    handle.hidden = true;
    root.classList.remove('is-interactive');
    x = y = targetX = targetY = 0;
  }

  // A failing enhancement must reveal the original SVG, including failures later
  // in event handlers or animation frames. Never replace or serialize HTML.
  function guarded(action) {
    return (...args) => {
      if (failed) return;
      try { action(...args); }
      catch {
        failed = true;
        staticArtwork();
        controls.hidden = true;
      }
    };
  }

  function draw() {
    const strands = ['', '', '', '']; // back -/+, front -/+
    let ribs = '';
    const point = (i, sign) => {
      const angle = i * Math.PI / 32 + phase;
      return [300 + sign * 62 * Math.sin(angle), 92 + i * 434 / 128];
    };
    const coord = p => p.map(v => v.toFixed(2)).join(',');
    for (let i = 0; i < 128; i++) {
      for (let strand = 0; strand < 2; strand++) {
        const sign = strand ? 1 : -1;
        const front = sign * Math.cos((i + .5) * Math.PI / 32 + phase) >= 0;
        strands[(front ? 2 : 0) + strand] += `M${coord(point(i, sign))}L${coord(point(i + 1, sign))}`;
      }
      if (i % 4 === 0) ribs += `M${coord(point(i, -1))}L${coord(point(i, 1))}`;
    }
    ribs += `M${coord(point(128, -1))}L${coord(point(128, 1))}`;
    paths[0].setAttribute('d', ribs);
    strands.forEach((d, i) => paths[i + 1].setAttribute('d', d));
    paintedPhase = phase;
  }

  const tick = guarded(timestamp => {
    frame = 0;
    if (!enabled || document.hidden) return;
    if (spinning) {
      // One turn in 20 seconds; cap a stalled frame instead of jumping ahead.
      if (lastTick !== null) setAngle(phase * 180 / Math.PI + Math.min(timestamp - lastTick, 64) * .018);
      lastTick = timestamp;
    }
    if (paintedPhase !== phase) draw();
    x += (targetX - x) * .18;
    y += (targetY - y) * .18;
    const moving = Math.abs(targetX - x) + Math.abs(targetY - y) > .02;
    if (!moving) { x = targetX; y = targetY; }
    field.setAttribute('transform', `translate(${x.toFixed(2)} ${y.toFixed(2)})`);
    if (moving || spinning) schedule();
  });
  function schedule() { if (enabled && !document.hidden && !frame) frame = requestAnimationFrame(tick); }
  function setAngle(degrees) {
    phase = ((degrees % 360 + 360) % 360) * Math.PI / 180;
    const value = Math.round(phase * 180 / Math.PI) % 360;
    if (handle.getAttribute('aria-valuenow') !== String(value)) {
      handle.setAttribute('aria-valuenow', String(value));
      handle.setAttribute('aria-valuetext', `${value} degrees`);
    }
  }
  function setPlaying(value) {
    spinning = value && enabled && !document.hidden;
    lastTick = null;
    play.textContent = spinning ? 'Pause' : 'Play';
    play.setAttribute('aria-label', spinning ? 'Pause helix rotation' : 'Play helix rotation');
    root.classList.toggle('is-playing', spinning);
    if (spinning) schedule();
  }
  function turn(degrees) {
    setPlaying(false);
    setAngle(degrees);
    schedule();
  }
  function updateMode() {
    staticArtwork();
    controls.hidden = motion.matches;
    mode.setAttribute('aria-pressed', String(paused));
    left.disabled = right.disabled = play.disabled = paused;
    if (paused || motion.matches) return;
    draw();
    drawing.removeAttribute('visibility');
    still.setAttribute('visibility', 'hidden');
    handle.hidden = false;
    enabled = true;
    root.classList.add('is-interactive');
  }
  function listen(target, event, action) { target.addEventListener(event, guarded(action)); }

  guarded(() => {
    drawing = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    drawing.id = 'orbital-moving-helix';
    drawing.setAttribute('visibility', 'hidden');
    paths = Array.from({length: 5}, (_, i) => {
      const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('fill', 'none');
      p.setAttribute('stroke', i === 0 ? '#aba4ff' : i < 3 ? '#8e8bce' : 'url(#orbital-strand)');
      p.setAttribute('stroke-width', i === 0 ? '1' : i < 3 ? '2' : '3');
      p.setAttribute('opacity', i === 0 ? '.38' : i < 3 ? '.55' : '1');
      drawing.appendChild(p);
      return p;
    });
    svg.insertBefore(drawing, still.nextSibling);
    listen(art, 'pointermove', e => {
      if (!enabled || drag || e.pointerType === 'touch') return;
      const box = art.getBoundingClientRect();
      const clamp = n => Math.max(-1, Math.min(1, n));
      targetX = clamp((e.clientX - box.left) / box.width * 2 - 1) * 6;
      targetY = clamp((e.clientY - box.top) / box.height * 2 - 1) * 4;
      schedule();
    });
    listen(art, 'pointerleave', () => { targetX = targetY = 0; schedule(); });
    listen(handle, 'pointerdown', e => {
      if (!enabled || !e.isPrimary || e.button !== 0 || drag) return;
      handle.focus({preventScroll: true});
      drag = {id: e.pointerId, x: e.clientX, y: e.clientY, phase, wasPlaying: spinning, active: false};
      setPlaying(false);
      if (e.pointerType !== 'touch') {
        e.preventDefault();
        handle.setPointerCapture(e.pointerId);
      }
    });
    listen(handle, 'pointermove', e => {
      if (!enabled || !drag || drag.id !== e.pointerId) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.active) {
        if (Math.abs(dy) > 8 && Math.abs(dy) >= Math.abs(dx)) { release(); return; }
        if (Math.abs(dx) < 8) return;
        drag.active = true;
        handle.setPointerCapture(e.pointerId);
        root.classList.add('is-dragging');
      }
      // One artwork width is a turn, independent of viewport/device resolution.
      turn(drag.phase * 180 / Math.PI + dx / art.getBoundingClientRect().width * 360);
    });
    listen(handle, 'pointerup', e => {
      if (!drag || drag.id !== e.pointerId) return;
      const previous = drag;
      release();
      if (enabled && paintedPhase !== phase) draw();
      if (!previous.active) setPlaying(!previous.wasPlaying);
    });
    for (const event of ['pointercancel', 'lostpointercapture', 'blur']) {
      listen(handle, event, () => {
        if (!drag) return;
        setPlaying(false);
        release();
        if (enabled && paintedPhase !== phase) draw();
      });
    }
    listen(handle, 'keydown', e => {
      if (!enabled) return;
      const delta = {ArrowLeft: -15, ArrowDown: -15, ArrowRight: 15, ArrowUp: 15};
      if (!(e.key in delta) && e.key !== 'Home' && e.key !== 'End') return;
      e.preventDefault();
      release();
      turn(e.key === 'Home' ? 0 : e.key === 'End' ? 359 : phase * 180 / Math.PI + delta[e.key]);
    });
    listen(left, 'click', () => { if (enabled) turn(phase * 180 / Math.PI - 15); });
    listen(right, 'click', () => { if (enabled) turn(phase * 180 / Math.PI + 15); });
    listen(play, 'click', () => { if (enabled) setPlaying(!spinning); });
    listen(mode, 'click', () => { paused = !paused; updateMode(); });
    listen(motion, 'change', updateMode);
    function stopInteraction() {
      setPlaying(false);
      release();
      if (enabled && paintedPhase !== phase) draw();
    }
    listen(root, 'focusout', e => { if (!root.contains(e.relatedTarget)) stopInteraction(); });
    listen(window, 'blur', stopInteraction);
    listen(document, 'visibilitychange', () => {
      if (document.hidden) { stopInteraction(); targetX = targetY = x = y = 0; cancelAnimationFrame(frame); frame = 0; field.removeAttribute('transform'); }
      else schedule();
    });
    updateMode();
  })();
})();
