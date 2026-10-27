(function (root) {
  'use strict';

  const ACTION_STATES = Object.freeze({
    reveal_answer: ['question'],
    rate_again: ['answer'],
    rate_known: ['answer']
  });
  const DEFAULT_BINDINGS = Object.freeze({
    reveal_answer: ['a', 'u', 's', 'i'],
    rate_again: ['a', 'u'],
    rate_known: ['s', 'i']
  });

  function normalizeKey(key) {
    const value = String(key || '').trim().toLowerCase();
    return /^[a-z]$/.test(value) ? value : null;
  }

  function resolveAction(key, phase, bindings) {
    const normalized = normalizeKey(key);
    if (!normalized) return null;
    for (const [action, phases] of Object.entries(ACTION_STATES)) {
      if (phases.includes(phase) && (bindings[action] || []).some(item => normalizeKey(item) === normalized)) {
        return action;
      }
    }
    return null;
  }

  function validateBindings(bindings) {
    const conflicts = [];
    const actions = Object.keys(ACTION_STATES);
    for (let i = 0; i < actions.length; i++) {
      for (let j = i + 1; j < actions.length; j++) {
        const left = actions[i], right = actions[j];
        if (!ACTION_STATES[left].some(state => ACTION_STATES[right].includes(state))) continue;
        const leftKeys = new Set((bindings[left] || []).map(normalizeKey).filter(Boolean));
        for (const key of (bindings[right] || []).map(normalizeKey).filter(Boolean)) {
          if (leftKeys.has(key)) conflicts.push({ key, actions: [left, right] });
        }
      }
    }
    return conflicts;
  }

  function attach({ documentRef, getPhase, actions, bindings = DEFAULT_BINDINGS, isBusy = () => false }) {
    if (validateBindings(bindings).length) throw new Error('Key bindings conflict in the same learning state');
    const pressed = new Set();
    const editable = element => {
      if (!element) return false;
      const tag = (element.tagName || '').toUpperCase();
      return ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || element.isContentEditable === true ||
        Boolean(element.closest && element.closest('[contenteditable="true"], [role="textbox"]'));
    };
    const onKeyDown = event => {
      const key = normalizeKey(event.key);
      if (!key || event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey ||
          editable(documentRef.activeElement) || isBusy()) return;
      if (pressed.has(key)) return;
      pressed.add(key);
      const action = resolveAction(key, getPhase(), bindings);
      if (action && typeof actions[action] === 'function') {
        event.preventDefault();
        actions[action]();
      }
    };
    const onKeyUp = event => pressed.delete(normalizeKey(event.key));
    const onBlur = () => pressed.clear();
    documentRef.addEventListener('keydown', onKeyDown);
    documentRef.addEventListener('keyup', onKeyUp);
    documentRef.defaultView?.addEventListener('blur', onBlur);
    return () => {
      documentRef.removeEventListener('keydown', onKeyDown);
      documentRef.removeEventListener('keyup', onKeyUp);
      documentRef.defaultView?.removeEventListener('blur', onBlur);
      pressed.clear();
    };
  }

  const api = { ACTION_STATES, DEFAULT_BINDINGS, normalizeKey, resolveAction, validateBindings, attach };
  root.EnglishOverlapKeys = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
