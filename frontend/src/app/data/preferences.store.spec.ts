import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { PreferencesStore } from './preferences.store';
import { PREF_TOGGLES } from '../features/preferences/preferences.data';

describe('PreferencesStore', () => {
  let store: PreferencesStore;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    store = TestBed.inject(PreferencesStore);
  });

  it('seeds toggles from defaults and starts clean', () => {
    for (const t of PREF_TOGGLES) {
      expect(store.toggles()[t.id]).toBe(t.defaultOn);
    }
    expect(store.lang()).toBe('en');
    expect(store.dirty()).toBe(false);
  });

  it('setToggle updates value and marks dirty', () => {
    const row = PREF_TOGGLES[0];
    const before = store.toggles()[row.id];
    store.setToggle(row.id, !before);
    expect(store.toggles()[row.id]).toBe(!before);
    expect(store.dirty()).toBe(true);
  });

  it('setLang updates code and marks dirty', () => {
    store.setLang('hi');
    expect(store.lang()).toBe('hi');
    expect(store.dirty()).toBe(true);
  });

  it('commit clears dirty flag without resetting values', () => {
    const row = PREF_TOGGLES[0];
    store.setToggle(row.id, !row.defaultOn);
    store.setLang('fr');
    store.commit();
    expect(store.dirty()).toBe(false);
    expect(store.toggles()[row.id]).toBe(!row.defaultOn);
    expect(store.lang()).toBe('fr');
  });

  it('discard restores defaults and clears dirty flag', () => {
    const row = PREF_TOGGLES[0];
    store.setToggle(row.id, !row.defaultOn);
    store.setLang('de');
    store.discard();
    expect(store.toggles()[row.id]).toBe(row.defaultOn);
    expect(store.lang()).toBe('en');
    expect(store.dirty()).toBe(false);
  });

  it('toggle updates are immutable (new object returned)', () => {
    const before = store.toggles();
    store.setToggle(PREF_TOGGLES[0].id, !PREF_TOGGLES[0].defaultOn);
    expect(store.toggles()).not.toBe(before);
  });
});
