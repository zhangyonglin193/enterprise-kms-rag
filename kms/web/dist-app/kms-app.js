var el = (e) => {
  throw TypeError(e);
};
var Zi = (e, t, s) => t.has(e) || el("Cannot " + s);
var tl = (e, t, s) => t.has(e) ? el("Cannot add the same private member more than once") : t instanceof WeakSet ? t.add(e) : t.set(e, s);
var Te = (e, t, s) => (Zi(e, t, "access private method"), s);
/**
* @vue/shared v3.5.44
* (c) 2018-present Yuxi (Evan) You and Vue contributors
* @license MIT
**/
// @__NO_SIDE_EFFECTS__
function In(e) {
  const t = /* @__PURE__ */ Object.create(null);
  for (const s of e.split(",")) t[s] = 1;
  return (s) => s in t;
}
const fe = {}, Kt = [], mt = () => {
}, Fl = () => !1, Ks = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // uppercase letter
(e.charCodeAt(2) > 122 || e.charCodeAt(2) < 97), Bs = (e) => e.startsWith("onUpdate:"), Fe = Object.assign, Rn = (e, t) => {
  const s = e.indexOf(t);
  s > -1 && e.splice(s, 1);
}, eo = Object.prototype.hasOwnProperty, oe = (e, t) => eo.call(e, t), Q = Array.isArray, Nt = (e) => ys(e) === "[object Map]", Jt = (e) => ys(e) === "[object Set]", sl = (e) => ys(e) === "[object Date]", te = (e) => typeof e == "function", me = (e) => typeof e == "string", lt = (e) => typeof e == "symbol", ce = (e) => e !== null && typeof e == "object", Ul = (e) => (ce(e) || te(e)) && te(e.then) && te(e.catch), Ll = Object.prototype.toString, ys = (e) => Ll.call(e), to = (e) => ys(e).slice(8, -1), Vl = (e) => ys(e) === "[object Object]", Nn = (e) => me(e) && e !== "NaN" && e[0] !== "-" && "" + parseInt(e, 10) === e, rs = /* @__PURE__ */ In(
  // the leading comma is intentional so empty string "" is also included
  ",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"
), qs = (e) => {
  const t = /* @__PURE__ */ Object.create(null);
  return ((s) => t[s] || (t[s] = e(s)));
}, so = /-\w/g, Ve = qs(
  (e) => e.replace(so, (t) => t.slice(1).toUpperCase())
), no = /\B([A-Z])/g, Ft = qs(
  (e) => e.replace(no, "-$1").toLowerCase()
), Ws = qs((e) => e.charAt(0).toUpperCase() + e.slice(1)), ln = qs(
  (e) => e ? `on${Ws(e)}` : ""
), vt = (e, t) => !Object.is(e, t), As = (e, ...t) => {
  for (let s = 0; s < e.length; s++)
    e[s](...t);
}, Hl = (e, t, s, n = !1) => {
  Object.defineProperty(e, t, {
    configurable: !0,
    enumerable: !1,
    writable: n,
    value: s
  });
}, Js = (e) => {
  const t = parseFloat(e);
  return isNaN(t) ? e : t;
};
let nl;
const zs = () => nl || (nl = typeof globalThis < "u" ? globalThis : typeof self < "u" ? self : typeof window < "u" ? window : typeof global < "u" ? global : {});
function es(e) {
  if (Q(e)) {
    const t = {};
    for (let s = 0; s < e.length; s++) {
      const n = e[s], l = me(n) ? ro(n) : es(n);
      if (l)
        for (const o in l)
          t[o] = l[o];
    }
    return t;
  } else if (me(e) || ce(e))
    return e;
}
const lo = /;(?![^(]*\))/g, io = /:([^]+)/, oo = /"(?:[^"\\]|\\[^])*"|'(?:[^'\\]|\\[^])*'|\\[^]|\/\*[^]*?\*\//g;
function ro(e) {
  const t = {};
  return e.replace(oo, (s) => s.startsWith("/*") ? "" : s).split(lo).forEach((s) => {
    if (s) {
      const n = s.split(io);
      n.length > 1 && (t[n[0].trim()] = n[1].trim());
    }
  }), t;
}
function ge(e) {
  let t = "";
  if (me(e))
    t = e;
  else if (Q(e))
    for (let s = 0; s < e.length; s++) {
      const n = ge(e[s]);
      n && (t += n + " ");
    }
  else if (ce(e))
    for (const s in e)
      e[s] && (t += s + " ");
  return t.trim();
}
const ao = "itemscope,allowfullscreen,formnovalidate,ismap,nomodule,novalidate,playsinline,readonly", uo = /* @__PURE__ */ In(ao);
function Kl(e) {
  return !!e || e === "";
}
function co(e, t, s) {
  if (e.length !== t.length) return !1;
  let n = !0;
  for (let l = 0; n && l < e.length; l++)
    n = jt(e[l], t[l], s);
  return n;
}
function ll(e, t, s) {
  if (e.size !== t.size) return !1;
  const n = Array.from(t), l = new Uint8Array(n.length);
  for (const o of e) {
    let a = -1;
    for (let r = 0; r < n.length; r++)
      if (!l[r] && jt(o, n[r], s)) {
        a = r;
        break;
      }
    if (a < 0) return !1;
    l[a] = 1;
  }
  return !0;
}
function fo(e, t, s) {
  let n = Nt(e), l = Nt(t);
  if (n || l || (n = Jt(e), l = Jt(t), n || l))
    return n && l ? ll(e, t, s) : !1;
  const o = Object.keys(e).length, a = Object.keys(t).length;
  if (o !== a)
    return !1;
  for (const r in e) {
    const c = e.hasOwnProperty(r), f = t.hasOwnProperty(r);
    if (c && !f || !c && f || !jt(e[r], t[r], s))
      return !1;
  }
  return String(e) === String(t);
}
function il(e, t, s, n) {
  s || (s = [/* @__PURE__ */ new Map(), /* @__PURE__ */ new Map()]);
  const [l, o] = s;
  if (l.has(e) || o.has(t))
    return l.get(e) === t && o.get(t) === e;
  l.set(e, t), o.set(t, e);
  const a = n(e, t, s);
  return l.delete(e), o.delete(t), a;
}
function jt(e, t, s) {
  if (e === t) return !0;
  let n = sl(e), l = sl(t);
  return n || l ? n && l ? e.getTime() === t.getTime() : !1 : (n = lt(e), l = lt(t), n || l ? e === t : (n = Q(e), l = Q(t), n || l ? n && l ? il(e, t, s, co) : !1 : (n = ce(e), l = ce(t), n || l ? !n || !l ? !1 : il(e, t, s, fo) : String(e) === String(t))));
}
function po(e, t) {
  return e.findIndex((s) => jt(s, t));
}
const Bl = (e) => !!(e && e.__v_isRef === !0), _ = (e) => me(e) ? e : e == null ? "" : Q(e) || ce(e) && (e.toString === Ll || !te(e.toString)) ? Bl(e) ? _(e.value) : JSON.stringify(e, ql, 2) : String(e), ql = (e, t) => Bl(t) ? ql(e, t.value) : Nt(t) ? {
  [`Map(${t.size})`]: [...t.entries()].reduce(
    (s, [n, l], o) => (s[on(n, o) + " =>"] = l, s),
    {}
  )
} : Jt(t) ? {
  [`Set(${t.size})`]: [...t.values()].map((s) => on(s))
} : lt(t) ? on(t) : ce(t) && !Q(t) && !Vl(t) ? String(t) : t, on = (e, t = "") => {
  var s;
  return (
    // Symbol.description in es2019+ so we need to cast here to pass
    // the lib: es2016 check
    lt(e) ? `Symbol(${(s = e.description) != null ? s : t})` : e
  );
};
/**
* @vue/reactivity v3.5.44
* (c) 2018-present Yuxi (Evan) You and Vue contributors
* @license MIT
**/
let Ie;
class ho {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t = !1) {
    this.detached = t, this._active = !0, this._on = 0, this.effects = [], this.cleanups = [], this._isPaused = !1, this._warnOnRun = !0, this.__v_skip = !0, !t && Ie && (Ie.active ? (this.parent = Ie, this.index = (Ie.scopes || (Ie.scopes = [])).push(
      this
    ) - 1) : (this._active = !1, this._warnOnRun = !1));
  }
  get active() {
    return this._active;
  }
  pause() {
    if (this._active) {
      this._isPaused = !0;
      let t, s;
      if (this.scopes) {
        const n = this.scopes.slice();
        for (t = 0, s = n.length; t < s; t++)
          n[t].pause();
      }
      for (t = 0, s = this.effects.length; t < s; t++)
        this.effects[t].pause();
    }
  }
  /**
   * Resumes the effect scope, including all child scopes and effects.
   */
  resume() {
    if (this._active && this._isPaused) {
      this._isPaused = !1;
      let t, s;
      if (this.scopes) {
        const l = this.scopes.slice();
        for (t = 0, s = l.length; t < s; t++)
          l[t].resume();
      }
      const n = this.effects.slice();
      for (t = 0, s = n.length; t < s; t++)
        n[t].resume();
    }
  }
  run(t) {
    if (this._active) {
      const s = Ie;
      try {
        return Ie = this, t();
      } finally {
        Ie = s;
      }
    }
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  on() {
    ++this._on === 1 && (this.prevScope = Ie, Ie = this);
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  off() {
    if (this._on > 0 && --this._on === 0) {
      if (Ie === this)
        Ie = this.prevScope;
      else {
        let t = Ie;
        for (; t; ) {
          if (t.prevScope === this) {
            t.prevScope = this.prevScope;
            break;
          }
          t = t.prevScope;
        }
      }
      this.prevScope = void 0;
    }
  }
  stop(t) {
    if (this._active) {
      this._active = !1;
      let s, n;
      for (s = 0, n = this.effects.length; s < n; s++)
        this.effects[s].stop();
      for (this.effects.length = 0, s = 0, n = this.cleanups.length; s < n; s++)
        this.cleanups[s]();
      if (this.cleanups.length = 0, this.scopes) {
        const l = this.scopes.slice();
        for (s = 0, n = l.length; s < n; s++)
          l[s].stop(!0);
        this.scopes.length = 0;
      }
      if (!this.detached && this.parent && !t) {
        const l = this.parent.scopes.pop();
        l && l !== this && (this.parent.scopes[this.index] = l, l.index = this.index);
      }
      this.parent = void 0;
    }
  }
}
function vo() {
  return Ie;
}
let he;
const rn = /* @__PURE__ */ new WeakSet();
class Wl {
  constructor(t) {
    this.fn = t, this.deps = void 0, this.depsTail = void 0, this.flags = 5, this.next = void 0, this.cleanup = void 0, this.scheduler = void 0, Ie && (Ie.active ? Ie.effects.push(this) : this.flags &= -2);
  }
  pause() {
    this.flags |= 64;
  }
  resume() {
    this.flags & 64 && (this.flags &= -65, rn.has(this) && (rn.delete(this), this.trigger()));
  }
  /**
   * @internal
   */
  notify() {
    this.flags & 2 && !(this.flags & 32) || this.flags & 8 || zl(this);
  }
  run() {
    if (!(this.flags & 1))
      return this.fn();
    this.flags |= 2, ol(this), Gl(this);
    const t = he, s = tt;
    he = this, tt = !0;
    try {
      return this.fn();
    } finally {
      Yl(this), he = t, tt = s, this.flags &= -3;
    }
  }
  stop() {
    if (this.flags & 1) {
      for (let t = this.deps; t; t = t.nextDep)
        Dn(t);
      this.deps = this.depsTail = void 0, ol(this), this.onStop && this.onStop(), this.flags &= -2;
    }
  }
  trigger() {
    this.flags & 64 ? rn.add(this) : this.scheduler ? this.scheduler() : this.runIfDirty();
  }
  /**
   * @internal
   */
  runIfDirty() {
    _n(this) && this.run();
  }
  get dirty() {
    return _n(this);
  }
}
let Jl = 0, as, us;
function zl(e, t = !1) {
  if (e.flags |= 8, t) {
    e.next = us, us = e;
    return;
  }
  e.next = as, as = e;
}
function Mn() {
  Jl++;
}
function jn() {
  if (--Jl > 0)
    return;
  if (us) {
    let t = us;
    for (us = void 0; t; ) {
      const s = t.next;
      t.next = void 0, t.flags &= -9, t = s;
    }
  }
  let e;
  for (; as; ) {
    let t = as;
    for (as = void 0; t; ) {
      const s = t.next;
      if (t.next = void 0, t.flags &= -9, t.flags & 1)
        try {
          t.trigger();
        } catch (n) {
          e || (e = n);
        }
      t = s;
    }
  }
  if (e) throw e;
}
function Gl(e) {
  for (let t = e.deps; t; t = t.nextDep)
    t.version = -1, t.prevActiveLink = t.dep.activeLink, t.dep.activeLink = t;
}
function Yl(e) {
  let t, s = e.depsTail, n = s;
  for (; n; ) {
    const l = n.prevDep;
    n.version === -1 ? (n === s && (s = l), Dn(n), mo(n)) : t = n, n.dep.activeLink = n.prevActiveLink, n.prevActiveLink = void 0, n = l;
  }
  e.deps = t, e.depsTail = s;
}
function _n(e) {
  for (let t = e.deps; t; t = t.nextDep)
    if (t.dep.version !== t.version || t.dep.computed && (Xl(t.dep.computed) || t.dep.version !== t.version))
      return !0;
  return !!e._dirty;
}
function Xl(e) {
  if (e.flags & 4 && !(e.flags & 16) || (e.flags &= -17, e.globalVersion === fs) || (e.globalVersion = fs, !e.isSSR && e.flags & 128 && (!e.deps && !e._dirty || !_n(e))))
    return;
  e.flags |= 2;
  const t = e.dep, s = he, n = tt;
  he = e, tt = !0;
  try {
    Gl(e);
    const l = e.fn(e._value);
    (t.version === 0 || vt(l, e._value)) && (e.flags |= 128, e._value = l, t.version++);
  } catch (l) {
    throw t.version++, l;
  } finally {
    he = s, tt = n, Yl(e), e.flags &= -3;
  }
}
function Dn(e, t = !1) {
  const { dep: s, prevSub: n, nextSub: l } = e;
  if (n && (n.nextSub = l, e.prevSub = void 0), l && (l.prevSub = n, e.nextSub = void 0), s.subs === e && (s.subs = n, !n && s.computed)) {
    s.computed.flags &= -5;
    for (let o = s.computed.deps; o; o = o.nextDep)
      Dn(o, !0);
  }
  !t && !--s.sc && s.map && s.map.delete(s.key);
}
function mo(e) {
  const { prevDep: t, nextDep: s } = e;
  t && (t.nextDep = s, e.prevDep = void 0), s && (s.prevDep = t, e.nextDep = void 0);
}
let tt = !0;
const Ql = [];
function _t() {
  Ql.push(tt), tt = !1;
}
function yt() {
  const e = Ql.pop();
  tt = e === void 0 ? !0 : e;
}
function ol(e) {
  const { cleanup: t } = e;
  if (e.cleanup = void 0, t) {
    const s = he;
    he = void 0;
    try {
      t();
    } finally {
      he = s;
    }
  }
}
let fs = 0;
class go {
  constructor(t, s) {
    this.sub = t, this.dep = s, this.version = s.version, this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
  }
}
class Fn {
  // TODO isolatedDeclarations "__v_skip"
  constructor(t) {
    this.computed = t, this.version = 0, this.activeLink = void 0, this.subs = void 0, this.map = void 0, this.key = void 0, this.sc = 0, this.__v_skip = !0;
  }
  track(t) {
    if (!he || !tt || he === this.computed)
      return;
    let s = this.activeLink;
    if (s === void 0 || s.sub !== he)
      s = this.activeLink = new go(he, this), he.deps ? (s.prevDep = he.depsTail, he.depsTail.nextDep = s, he.depsTail = s) : he.deps = he.depsTail = s, Zl(s);
    else if (s.version === -1 && (s.version = this.version, s.nextDep)) {
      const n = s.nextDep;
      n.prevDep = s.prevDep, s.prevDep && (s.prevDep.nextDep = n), s.prevDep = he.depsTail, s.nextDep = void 0, he.depsTail.nextDep = s, he.depsTail = s, he.deps === s && (he.deps = n);
    }
    return s;
  }
  trigger(t) {
    this.version++, fs++, this.notify(t);
  }
  notify(t) {
    Mn();
    try {
      for (let s = this.subs; s; s = s.prevSub)
        s.sub.notify() && s.sub.dep.notify();
    } finally {
      jn();
    }
  }
}
function Zl(e) {
  if (e.dep.sc++, e.sub.flags & 4) {
    const t = e.dep.computed;
    if (t && !e.dep.subs) {
      t.flags |= 20;
      for (let n = t.deps; n; n = n.nextDep)
        Zl(n);
    }
    const s = e.dep.subs;
    s !== e && (e.prevSub = s, s && (s.nextSub = e)), e.dep.subs = e;
  }
}
const yn = /* @__PURE__ */ new WeakMap(), Wt = /* @__PURE__ */ Symbol(
  ""
), bn = /* @__PURE__ */ Symbol(
  ""
), ps = /* @__PURE__ */ Symbol(
  ""
);
function Ne(e, t, s) {
  if (tt && he) {
    let n = yn.get(e);
    n || yn.set(e, n = /* @__PURE__ */ new Map());
    let l = n.get(s);
    l || (n.set(s, l = new Fn()), l.map = n, l.key = s), l.track();
  }
}
function St(e, t, s, n, l, o) {
  const a = yn.get(e);
  if (!a) {
    fs++;
    return;
  }
  const r = (c) => {
    c && c.trigger();
  };
  if (Mn(), t === "clear")
    a.forEach(r);
  else {
    const c = Q(e), f = c && Nn(s);
    if (c && s === "length") {
      const h = Number(n);
      a.forEach((k, R) => {
        (R === "length" || R === ps || !lt(R) && R >= h) && r(k);
      });
    } else
      switch ((s !== void 0 || a.has(void 0)) && r(a.get(s)), f && r(a.get(ps)), t) {
        case "add":
          c ? f && r(a.get("length")) : (r(a.get(Wt)), Nt(e) && r(a.get(bn)));
          break;
        case "delete":
          c || (r(a.get(Wt)), Nt(e) && r(a.get(bn)));
          break;
        case "set":
          Nt(e) && r(a.get(Wt));
          break;
      }
  }
  jn();
}
function Gt(e) {
  const t = /* @__PURE__ */ ae(e);
  return t === e || (Ne(t, "iterate", ps), /* @__PURE__ */ Ge(e)) ? t : /* @__PURE__ */ bt(e) ? /* @__PURE__ */ Mt(e) ? t.map((s) => Dt(Ye(s))) : t.map(Dt) : t.map(Ye);
}
function Gs(e) {
  return Ne(e = /* @__PURE__ */ ae(e), "iterate", ps), e;
}
function ft(e, t) {
  return /* @__PURE__ */ bt(e) ? Dt(/* @__PURE__ */ Mt(e) ? Ye(t) : t) : Ye(t);
}
const _o = {
  __proto__: null,
  [Symbol.iterator]() {
    return an(this, Symbol.iterator, (e) => ft(this, e));
  },
  concat(...e) {
    return Gt(this).concat(
      ...e.map((t) => Q(t) ? Gt(t) : t)
    );
  },
  entries() {
    return an(this, "entries", (e) => (e[1] = ft(this, e[1]), e));
  },
  every(e, t) {
    return kt(this, "every", e, t, void 0, arguments);
  },
  filter(e, t) {
    return kt(
      this,
      "filter",
      e,
      t,
      (s) => s.map((n) => ft(this, n)),
      arguments
    );
  },
  find(e, t) {
    return kt(
      this,
      "find",
      e,
      t,
      (s) => ft(this, s),
      arguments
    );
  },
  findIndex(e, t) {
    return kt(this, "findIndex", e, t, void 0, arguments);
  },
  findLast(e, t) {
    return kt(
      this,
      "findLast",
      e,
      t,
      (s) => ft(this, s),
      arguments
    );
  },
  findLastIndex(e, t) {
    return kt(this, "findLastIndex", e, t, void 0, arguments);
  },
  // flat, flatMap could benefit from ARRAY_ITERATE but are not straight-forward to implement
  forEach(e, t) {
    return kt(this, "forEach", e, t, void 0, arguments);
  },
  includes(...e) {
    return un(this, "includes", e);
  },
  indexOf(...e) {
    return un(this, "indexOf", e);
  },
  join(e) {
    return Gt(this).join(e);
  },
  // keys() iterator only reads `length`, no optimization required
  lastIndexOf(...e) {
    return un(this, "lastIndexOf", e);
  },
  map(e, t) {
    return kt(this, "map", e, t, void 0, arguments);
  },
  pop() {
    return ss(this, "pop");
  },
  push(...e) {
    return ss(this, "push", e);
  },
  reduce(e, ...t) {
    return al(this, "reduce", e, t);
  },
  reduceRight(e, ...t) {
    return al(this, "reduceRight", e, t);
  },
  shift() {
    return ss(this, "shift");
  },
  // slice could use ARRAY_ITERATE but also seems to beg for range tracking
  some(e, t) {
    return kt(this, "some", e, t, void 0, arguments);
  },
  splice(...e) {
    return ss(this, "splice", e);
  },
  toReversed() {
    return Gt(this).toReversed();
  },
  toSorted(e) {
    return Gt(this).toSorted(e);
  },
  toSpliced(...e) {
    return Gt(this).toSpliced(...e);
  },
  unshift(...e) {
    return ss(this, "unshift", e);
  },
  values() {
    return an(this, "values", (e) => ft(this, e));
  }
};
function an(e, t, s) {
  const n = Gs(e), l = n[t], o = l.call(n);
  if (n !== e && !/* @__PURE__ */ Ge(e)) {
    if (o[Symbol.toStringTag] === "Array Iterator") {
      const a = Object.create(Object.getPrototypeOf(o));
      return a.next = () => rl(o.next(), s), l !== ei[t] && Object.defineProperties(a, {
        return: {
          get() {
            const r = o.return;
            return typeof r == "function" ? r.bind(o) : r;
          }
        },
        throw: {
          get() {
            const r = o.throw;
            return typeof r == "function" ? r.bind(o) : r;
          }
        }
      }), a;
    }
    o._next = o.next, o.next = () => rl(o._next(), s);
  }
  return o;
}
function rl(e, t) {
  return e.done || (e.value = t(e.value)), e;
}
const ei = Array.prototype;
function kt(e, t, s, n, l, o) {
  const a = Gs(e), r = a !== e && !/* @__PURE__ */ Ge(e), c = a[t];
  if (c !== ei[t]) {
    const k = c.apply(e, o);
    return r ? Ye(k) : k;
  }
  let f = s;
  a !== e && (r ? f = function(k, R) {
    return s.call(this, ft(e, k), R, e);
  } : s.length > 2 && (f = function(k, R) {
    return s.call(this, k, R, e);
  }));
  const h = c.call(a, f, n);
  return r && l ? l(h) : h;
}
function al(e, t, s, n) {
  const l = Gs(e), o = l !== e && !/* @__PURE__ */ Ge(e);
  let a = s, r = !1;
  l !== e && (o ? (r = n.length === 0, a = function(f, h, k) {
    return r && (r = !1, f = ft(e, f)), s.call(this, f, ft(e, h), k, e);
  }) : s.length > 3 && (a = function(f, h, k) {
    return s.call(this, f, h, k, e);
  }));
  const c = l[t](a, ...n);
  return r ? ft(e, c) : c;
}
function un(e, t, s) {
  const n = /* @__PURE__ */ ae(e);
  Ne(n, "iterate", ps);
  const l = n[t](...s);
  return (l === -1 || l === !1) && /* @__PURE__ */ Vn(s[0]) ? (s[0] = /* @__PURE__ */ ae(s[0]), n[t](...s)) : l;
}
function ss(e, t, s = []) {
  _t(), Mn();
  const n = (/* @__PURE__ */ ae(e))[t].apply(e, s);
  return jn(), yt(), n;
}
const yo = /* @__PURE__ */ In("__proto__,__v_isRef,__isVue"), ti = new Set(
  /* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((e) => e !== "arguments" && e !== "caller").map((e) => Symbol[e]).filter(lt)
);
function bo(e) {
  lt(e) || (e = String(e));
  const t = /* @__PURE__ */ ae(this);
  return Ne(t, "has", e), t.hasOwnProperty(e);
}
class si {
  constructor(t = !1, s = !1) {
    this._isReadonly = t, this._isShallow = s;
  }
  get(t, s, n) {
    if (s === "__v_skip") return t.__v_skip;
    const l = this._isReadonly, o = this._isShallow;
    if (s === "__v_isReactive")
      return !l;
    if (s === "__v_isReadonly")
      return l;
    if (s === "__v_isShallow")
      return o;
    if (s === "__v_raw")
      return n === (l ? o ? Eo : oi : o ? ii : li).get(t) || // receiver is not the reactive proxy, but has the same prototype
      // this means the receiver is a user proxy of the reactive proxy
      Object.getPrototypeOf(t) === Object.getPrototypeOf(n) ? t : void 0;
    const a = Q(t);
    if (!l) {
      let c;
      if (a && (c = _o[s]))
        return c;
      if (s === "hasOwnProperty")
        return bo;
    }
    const r = Reflect.get(
      t,
      s,
      // if this is a proxy wrapping a ref, return methods using the raw ref
      // as receiver so that we don't have to call `toRaw` on the ref in all
      // its class methods
      /* @__PURE__ */ De(t) ? t : n
    );
    if ((lt(s) ? ti.has(s) : yo(s)) || (l || Ne(t, "get", s), o))
      return r;
    if (/* @__PURE__ */ De(r)) {
      const c = a && Nn(s) ? r : r.value;
      return l && ce(c) ? /* @__PURE__ */ $n(c) : c;
    }
    return ce(r) ? l ? /* @__PURE__ */ $n(r) : /* @__PURE__ */ bs(r) : r;
  }
}
class ni extends si {
  constructor(t = !1) {
    super(!1, t);
  }
  set(t, s, n, l) {
    let o = t[s];
    const a = Q(t) && Nn(s);
    if (!this._isShallow) {
      const f = /* @__PURE__ */ bt(o);
      if (!/* @__PURE__ */ Ge(n) && !/* @__PURE__ */ bt(n) && (o = /* @__PURE__ */ ae(o), n = /* @__PURE__ */ ae(n)), !a && /* @__PURE__ */ De(o) && !/* @__PURE__ */ De(n))
        return f || (o.value = n), !0;
    }
    const r = a ? Number(s) < t.length : oe(t, s), c = Reflect.set(
      t,
      s,
      n,
      /* @__PURE__ */ De(t) ? t : l
    );
    return t === /* @__PURE__ */ ae(l) && c && (r ? vt(n, o) && St(t, "set", s, n) : St(t, "add", s, n)), c;
  }
  deleteProperty(t, s) {
    const n = oe(t, s);
    t[s];
    const l = Reflect.deleteProperty(t, s);
    return l && n && St(t, "delete", s, void 0), l;
  }
  has(t, s) {
    const n = Reflect.has(t, s);
    return (!lt(s) || !ti.has(s)) && Ne(t, "has", s), n;
  }
  ownKeys(t) {
    return Ne(
      t,
      "iterate",
      Q(t) ? "length" : Wt
    ), Reflect.ownKeys(t);
  }
}
class ko extends si {
  constructor(t = !1) {
    super(!0, t);
  }
  set(t, s) {
    return !0;
  }
  deleteProperty(t, s) {
    return !0;
  }
}
const $o = /* @__PURE__ */ new ni(), wo = /* @__PURE__ */ new ko(), xo = /* @__PURE__ */ new ni(!0);
const kn = (e) => e, ws = (e) => Reflect.getPrototypeOf(e);
function So(e, t, s) {
  return function(...n) {
    const l = this.__v_raw, o = /* @__PURE__ */ ae(l), a = Nt(o), r = e === "entries" || e === Symbol.iterator && a, c = e === "keys" && a, f = l[e](...n), h = s ? kn : t ? Dt : Ye;
    return !t && Ne(
      o,
      "iterate",
      c ? bn : Wt
    ), Fe(
      // inheriting all iterator properties
      Object.create(f),
      {
        // iterator protocol
        next() {
          const { value: k, done: R } = f.next();
          return R ? { value: k, done: R } : {
            value: r ? [h(k[0]), h(k[1])] : h(k),
            done: R
          };
        }
      }
    );
  };
}
function xs(e) {
  return function(...t) {
    return e === "delete" ? !1 : e === "clear" ? void 0 : this;
  };
}
function Co(e, t) {
  const s = {
    get(l) {
      const o = this.__v_raw, a = /* @__PURE__ */ ae(o), r = /* @__PURE__ */ ae(l);
      e || (vt(l, r) && Ne(a, "get", l), Ne(a, "get", r));
      const { has: c } = ws(a), f = t ? kn : e ? Dt : Ye;
      if (c.call(a, l))
        return f(o.get(l));
      if (c.call(a, r))
        return f(o.get(r));
      o !== a && o.get(l);
    },
    get size() {
      const l = this.__v_raw;
      return !e && Ne(/* @__PURE__ */ ae(l), "iterate", Wt), l.size;
    },
    has(l) {
      const o = this.__v_raw, a = /* @__PURE__ */ ae(o), r = /* @__PURE__ */ ae(l);
      return e || (vt(l, r) && Ne(a, "has", l), Ne(a, "has", r)), l === r ? o.has(l) : o.has(l) || o.has(r);
    },
    forEach(l, o) {
      const a = this, r = a.__v_raw, c = /* @__PURE__ */ ae(r), f = t ? kn : e ? Dt : Ye;
      return !e && Ne(c, "iterate", Wt), r.forEach((h, k) => l.call(o, f(h), f(k), a));
    }
  };
  return Fe(
    s,
    e ? {
      add: xs("add"),
      set: xs("set"),
      delete: xs("delete"),
      clear: xs("clear")
    } : {
      add(l) {
        const o = /* @__PURE__ */ ae(this), a = ws(o), r = /* @__PURE__ */ ae(l), c = !t && !/* @__PURE__ */ Ge(l) && !/* @__PURE__ */ bt(l) ? r : l;
        return a.has.call(o, c) || vt(l, c) && a.has.call(o, l) || vt(r, c) && a.has.call(o, r) || (o.add(c), St(o, "add", c, c)), this;
      },
      set(l, o) {
        !t && !/* @__PURE__ */ Ge(o) && !/* @__PURE__ */ bt(o) && (o = /* @__PURE__ */ ae(o));
        const a = /* @__PURE__ */ ae(this), { has: r, get: c } = ws(a);
        let f = r.call(a, l);
        f || (l = /* @__PURE__ */ ae(l), f = r.call(a, l));
        const h = c.call(a, l);
        return a.set(l, o), f ? vt(o, h) && St(a, "set", l, o) : St(a, "add", l, o), this;
      },
      delete(l) {
        const o = /* @__PURE__ */ ae(this), { has: a, get: r } = ws(o);
        let c = a.call(o, l);
        c || (l = /* @__PURE__ */ ae(l), c = a.call(o, l)), r && r.call(o, l);
        const f = o.delete(l);
        return c && St(o, "delete", l, void 0), f;
      },
      clear() {
        const l = /* @__PURE__ */ ae(this), o = l.size !== 0, a = l.clear();
        return o && St(
          l,
          "clear",
          void 0,
          void 0
        ), a;
      }
    }
  ), [
    "keys",
    "values",
    "entries",
    Symbol.iterator
  ].forEach((l) => {
    s[l] = So(l, e, t);
  }), s;
}
function Un(e, t) {
  const s = Co(e, t);
  return (n, l, o) => l === "__v_isReactive" ? !e : l === "__v_isReadonly" ? e : l === "__v_isShallow" ? t : l === "__v_raw" ? n : Reflect.get(
    oe(s, l) && l in n ? s : n,
    l,
    o
  );
}
const To = {
  get: /* @__PURE__ */ Un(!1, !1)
}, Ao = {
  get: /* @__PURE__ */ Un(!1, !0)
}, Oo = {
  get: /* @__PURE__ */ Un(!0, !1)
};
const li = /* @__PURE__ */ new WeakMap(), ii = /* @__PURE__ */ new WeakMap(), oi = /* @__PURE__ */ new WeakMap(), Eo = /* @__PURE__ */ new WeakMap();
function Po(e) {
  switch (e) {
    case "Object":
    case "Array":
      return 1;
    case "Map":
    case "Set":
    case "WeakMap":
    case "WeakSet":
      return 2;
    default:
      return 0;
  }
}
// @__NO_SIDE_EFFECTS__
function bs(e) {
  return /* @__PURE__ */ bt(e) ? e : Ln(
    e,
    !1,
    $o,
    To,
    li
  );
}
// @__NO_SIDE_EFFECTS__
function Io(e) {
  return Ln(
    e,
    !1,
    xo,
    Ao,
    ii
  );
}
// @__NO_SIDE_EFFECTS__
function $n(e) {
  return Ln(
    e,
    !0,
    wo,
    Oo,
    oi
  );
}
function Ln(e, t, s, n, l) {
  if (!ce(e) || e.__v_raw && !(t && e.__v_isReactive) || e.__v_skip || !Object.isExtensible(e))
    return e;
  const o = l.get(e);
  if (o)
    return o;
  const a = Po(to(e));
  if (a === 0)
    return e;
  const r = new Proxy(
    e,
    a === 2 ? n : s
  );
  return l.set(e, r), r;
}
// @__NO_SIDE_EFFECTS__
function Mt(e) {
  return /* @__PURE__ */ bt(e) ? /* @__PURE__ */ Mt(e.__v_raw) : !!(e && e.__v_isReactive);
}
// @__NO_SIDE_EFFECTS__
function bt(e) {
  return !!(e && e.__v_isReadonly);
}
// @__NO_SIDE_EFFECTS__
function Ge(e) {
  return !!(e && e.__v_isShallow);
}
// @__NO_SIDE_EFFECTS__
function Vn(e) {
  return e ? !!e.__v_raw : !1;
}
// @__NO_SIDE_EFFECTS__
function ae(e) {
  const t = e && e.__v_raw;
  return t ? /* @__PURE__ */ ae(t) : e;
}
function Ro(e) {
  return !oe(e, "__v_skip") && Object.isExtensible(e) && Hl(e, "__v_skip", !0), e;
}
const Ye = (e) => ce(e) ? /* @__PURE__ */ bs(e) : e, Dt = (e) => ce(e) ? /* @__PURE__ */ $n(e) : e;
// @__NO_SIDE_EFFECTS__
function De(e) {
  return e ? e.__v_isRef === !0 : !1;
}
// @__NO_SIDE_EFFECTS__
function H(e) {
  return No(e, !1);
}
function No(e, t) {
  return /* @__PURE__ */ De(e) ? e : new Mo(e, t);
}
class Mo {
  constructor(t, s) {
    this.dep = new Fn(), this.__v_isRef = !0, this.__v_isShallow = !1, this._rawValue = s ? t : /* @__PURE__ */ ae(t), this._value = s ? t : Ye(t), this.__v_isShallow = s;
  }
  get value() {
    return this.dep.track(), this._value;
  }
  set value(t) {
    const s = this._rawValue, n = this.__v_isShallow || /* @__PURE__ */ Ge(t) || /* @__PURE__ */ bt(t);
    t = n ? t : /* @__PURE__ */ ae(t), vt(t, s) && (this._rawValue = t, this._value = n ? t : Ye(t), this.dep.trigger());
  }
}
function ie(e) {
  return /* @__PURE__ */ De(e) ? e.value : e;
}
const jo = {
  get: (e, t, s) => t === "__v_raw" ? e : ie(Reflect.get(e, t, s)),
  set: (e, t, s, n) => {
    const l = e[t];
    return /* @__PURE__ */ De(l) && !/* @__PURE__ */ De(s) ? (l.value = s, !0) : Reflect.set(e, t, s, n);
  }
};
function ri(e) {
  return /* @__PURE__ */ Mt(e) ? e : new Proxy(e, jo);
}
class Do {
  constructor(t, s, n) {
    this.fn = t, this.setter = s, this._value = void 0, this.dep = new Fn(this), this.__v_isRef = !0, this.deps = void 0, this.depsTail = void 0, this.flags = 16, this.globalVersion = fs - 1, this.next = void 0, this.effect = this, this.__v_isReadonly = !s, this.isSSR = n;
  }
  /**
   * @internal
   */
  notify() {
    if (this.flags |= 16, !(this.flags & 8) && // avoid infinite self recursion
    he !== this)
      return zl(this, !0), !0;
  }
  get value() {
    const t = this.dep.track();
    return Xl(this), t && (t.version = this.dep.version), this._value;
  }
  set value(t) {
    this.setter && this.setter(t);
  }
}
// @__NO_SIDE_EFFECTS__
function Fo(e, t, s = !1) {
  let n, l;
  return te(e) ? n = e : (n = e.get, l = e.set), new Do(n, l, s);
}
const Ss = {}, Is = /* @__PURE__ */ new WeakMap();
let Vt;
function Uo(e, t = !1, s = Vt) {
  if (s) {
    let n = Is.get(s);
    n || Is.set(s, n = []), n.push(e);
  }
}
function Lo(e, t, s = fe) {
  const { immediate: n, deep: l, once: o, scheduler: a, augmentJob: r, call: c } = s, f = (I) => l ? I : /* @__PURE__ */ Ge(I) || l === !1 || l === 0 ? Ct(I, 1) : Ct(I);
  let h, k, R, O, C = !1, j = !1;
  if (/* @__PURE__ */ De(e) ? (k = () => e.value, C = /* @__PURE__ */ Ge(e)) : /* @__PURE__ */ Mt(e) ? (k = () => f(e), C = !0) : Q(e) ? (j = !0, C = e.some((I) => /* @__PURE__ */ Mt(I) || /* @__PURE__ */ Ge(I)), k = () => e.map((I) => {
    if (/* @__PURE__ */ De(I))
      return I.value;
    if (/* @__PURE__ */ Mt(I))
      return f(I);
    if (te(I))
      return c ? c(I, 2) : I();
  })) : te(e) ? t ? k = c ? () => c(e, 2) : e : k = () => {
    if (R) {
      _t();
      try {
        R();
      } finally {
        yt();
      }
    }
    const I = Vt;
    Vt = h;
    try {
      return c ? c(e, 3, [O]) : e(O);
    } finally {
      Vt = I;
    }
  } : k = mt, t && l) {
    const I = k, X = l === !0 ? 1 / 0 : l;
    k = () => Ct(I(), X);
  }
  const D = vo(), se = () => {
    h.stop(), D && D.active && Rn(D.effects, h);
  };
  if (o && t) {
    const I = t;
    t = (...X) => {
      try {
        return I(...X);
      } finally {
        se();
      }
    };
  }
  let U = j ? new Array(e.length).fill(Ss) : Ss;
  const L = (I) => {
    if (!(!(h.flags & 1) || !h.dirty && !I))
      if (t) {
        const X = h.run();
        if (I || l || C || (j ? X.some((ve, _e) => vt(ve, U[_e])) : vt(X, U))) {
          const ve = Vt;
          _t();
          try {
            R && R(), Vt = h;
            const _e = [
              X,
              // pass undefined as the old value when it's changed for the first time
              U === Ss ? void 0 : j && U[0] === Ss ? [] : U,
              O
            ];
            U = X, c ? c(t, 3, _e) : (
              // @ts-expect-error
              t(..._e)
            );
          } finally {
            Vt = ve, yt();
          }
        }
      } else
        h.run();
  };
  return r && r(L), h = new Wl(k), h.scheduler = a ? () => a(L, !1) : L, O = (I) => Uo(I, !1, h), R = h.onStop = () => {
    const I = Is.get(h);
    if (I) {
      if (c)
        c(I, 4);
      else
        for (const X of I) X();
      Is.delete(h);
    }
  }, t ? n ? L(!0) : U = h.run() : a ? a(L.bind(null, !0), !0) : h.run(), se.pause = h.pause.bind(h), se.resume = h.resume.bind(h), se.stop = se, se;
}
function Ct(e, t = 1 / 0, s) {
  if (t <= 0 || !ce(e) || e.__v_skip || (s = s || /* @__PURE__ */ new Map(), (s.get(e) || 0) >= t))
    return e;
  if (s.set(e, t), t--, /* @__PURE__ */ De(e))
    Ct(e.value, t, s);
  else if (Q(e))
    for (let n = 0; n < e.length; n++)
      Ct(e[n], t, s);
  else if (Jt(e) || Nt(e))
    e.forEach((n) => {
      Ct(n, t, s);
    });
  else if (Vl(e)) {
    for (const n in e)
      Ct(e[n], t, s);
    for (const n of Object.getOwnPropertySymbols(e))
      Object.prototype.propertyIsEnumerable.call(e, n) && Ct(e[n], t, s);
  }
  return e;
}
/**
* @vue/runtime-core v3.5.44
* (c) 2018-present Yuxi (Evan) You and Vue contributors
* @license MIT
**/
function ks(e, t, s, n) {
  try {
    return n ? e(...n) : e();
  } catch (l) {
    Ys(l, t, s);
  }
}
function it(e, t, s, n) {
  if (te(e)) {
    const l = ks(e, t, s, n);
    return l && Ul(l) && l.catch((o) => {
      Ys(o, t, s);
    }), l;
  }
  if (Q(e)) {
    const l = [];
    for (let o = 0; o < e.length; o++)
      l.push(it(e[o], t, s, n));
    return l;
  }
}
function Ys(e, t, s, n = !0) {
  const l = t ? t.vnode : null, { errorHandler: o, throwUnhandledErrorInProduction: a } = t && t.appContext.config || fe;
  if (t) {
    let r = t.parent;
    const c = t.proxy, f = `https://vuejs.org/error-reference/#runtime-${s}`;
    for (; r; ) {
      const h = r.ec;
      if (h) {
        for (let k = 0; k < h.length; k++)
          if (h[k](e, c, f) === !1)
            return;
      }
      r = r.parent;
    }
    if (o) {
      _t(), ks(o, null, 10, [
        e,
        c,
        f
      ]), yt();
      return;
    }
  }
  Vo(e, s, l, n, a);
}
function Vo(e, t, s, n = !0, l = !1) {
  if (l)
    throw e;
  console.error(e);
}
const Le = [];
let et = -1;
const pt = [];
let It = null, Yt = 0;
const ai = /* @__PURE__ */ Promise.resolve();
let Rs = null;
function Ns(e) {
  const t = Rs || ai;
  return e ? t.then(this ? e.bind(this) : e) : t;
}
function Ho(e) {
  let t = et + 1, s = Le.length;
  for (; t < s; ) {
    const n = t + s >>> 1, l = Le[n], o = hs(l);
    o < e || o === e && l.flags & 2 ? t = n + 1 : s = n;
  }
  return t;
}
function Hn(e) {
  if (!(e.flags & 1)) {
    const t = hs(e), s = Le[Le.length - 1];
    !s || // fast path when the job id is larger than the tail
    !(e.flags & 2) && t >= hs(s) ? Le.push(e) : Le.splice(Ho(t), 0, e), e.flags |= 1, ui();
  }
}
function ui() {
  Rs || (Rs = ai.then(fi));
}
function Ko(e) {
  if (!Q(e))
    It && e.id === -1 ? It.splice(Yt + 1, 0, e) : e.flags & 1 || (pt.push(e), e.flags |= 1);
  else
    for (let t = 0; t < e.length; t++)
      pt.push(e[t]);
  ui();
}
function ci(e, t, s, n = et + 1) {
  for (; n < Le.length; n++) {
    const l = Le[n];
    if (l && l.flags & 2) {
      if (e && l.id !== e.uid || t !== void 0 && !(l.id >= t))
        continue;
      Le.splice(n, 1), n = e ? n - 1 : et, l.flags & 4 && (l.flags &= -2), l(), l.flags & 4 || (l.flags &= -2);
    }
  }
}
function di(e, t, s = 0) {
  if (pt.length) {
    let n = pt, l = 0;
    if (t) {
      n = [];
      for (let a = 0; a < pt.length; a++) {
        const r = pt[a];
        (r.i !== void 0 ? !r.i || r.i.uid < s : t.has(r)) ? pt[l++] = r : n.push(r);
      }
    }
    const o = [...new Set(n)].sort((a, r) => hs(a) - hs(r));
    if (pt.length = l, It) {
      for (let a = 0; a < o.length; a++)
        It.push(o[a]);
      return;
    }
    for (It = o, Yt = 0; Yt < It.length; Yt++) {
      const a = It[Yt];
      a.flags & 4 && (a.flags &= -2), a.flags & 8 || a(), a.flags &= -2;
    }
    It = null, Yt = 0;
  }
}
let cn = !1;
function Bo(e, t) {
  if (cn) {
    e();
    return;
  }
  const s = t === void 0 ? void 0 : new Set(pt);
  e(), cn = !0;
  try {
    ci(void 0, t), di(void 0, s, t);
  } finally {
    cn = !1;
  }
}
const hs = (e) => e.id == null ? e.flags & 2 ? -1 : 1 / 0 : e.id;
function fi(e) {
  try {
    for (et = 0; et < Le.length; et++) {
      const t = Le[et];
      t && !(t.flags & 8) && (t.flags & 4 && (t.flags &= -2), ks(
        t,
        t.i,
        t.i ? 15 : 14
      ), t.flags & 4 || (t.flags &= -2));
    }
  } finally {
    for (; et < Le.length; et++) {
      const t = Le[et];
      t && (t.flags &= -2);
    }
    et = -1, Le.length = 0, di(), Rs = null, (Le.length || pt.length) && fi();
  }
}
let Re = null, pi = null;
function Ms(e) {
  const t = Re;
  return Re = e, pi = e && e.type.__scopeId || null, t;
}
function qo(e, t = Re, s) {
  if (!t || e._n)
    return e;
  const n = (...l) => {
    n._d && bl(-1);
    const o = Ms(t), a = Tt.length;
    let r;
    try {
      r = e(...l);
    } finally {
      for (let c = Tt.length; c > a; c--) Jn();
      Ms(o), n._d && bl(1);
    }
    return r;
  };
  return n._n = !0, n._c = !0, n._d = !0, n;
}
function ke(e, t) {
  if (Re === null)
    return e;
  const s = sn(Re), n = e.dirs || (e.dirs = []);
  for (let l = 0; l < t.length; l++) {
    let [o, a, r, c = fe] = t[l];
    o && (te(o) && (o = {
      mounted: o,
      updated: o
    }), o.deep && Ct(a), n.push({
      dir: o,
      instance: s,
      value: a,
      oldValue: void 0,
      arg: r,
      modifiers: c
    }));
  }
  return e;
}
function Ut(e, t, s, n) {
  const l = e.dirs, o = t && t.dirs;
  for (let a = 0; a < l.length; a++) {
    const r = l[a];
    o && (r.oldValue = o[a].value);
    let c = r.dir[n];
    c && (_t(), it(c, s, 8, [
      e.el,
      r,
      e,
      t
    ]), yt());
  }
}
function Wo(e, t) {
  if (je) {
    let s = je.provides;
    const n = je.parent && je.parent.provides;
    n === s && (s = je.provides = Object.create(n)), s[e] = t;
  }
}
function Os(e, t, s = !1) {
  const n = Br();
  if (n || Qt) {
    let l = Qt ? Qt._context.provides : n ? n.parent == null || n.ce ? n.vnode.appContext && n.vnode.appContext.provides : n.parent.provides : void 0;
    if (l && e in l)
      return l[e];
    if (arguments.length > 1)
      return s && te(t) ? t.call(n && n.proxy) : t;
  }
}
const Jo = /* @__PURE__ */ Symbol.for("v-scx"), zo = () => Os(Jo);
function st(e, t, s) {
  return hi(e, t, s);
}
function hi(e, t, s = fe) {
  const { immediate: n, deep: l, flush: o, once: a } = s, r = Fe({}, s), c = t && n || !t && o !== "post";
  let f;
  if (gs) {
    if (o === "sync") {
      const O = zo();
      f = O.__watcherHandles || (O.__watcherHandles = []);
    } else if (!c) {
      const O = () => {
      };
      return O.stop = mt, O.resume = mt, O.pause = mt, O;
    }
  }
  const h = je;
  r.call = (O, C, j) => it(O, h, C, j);
  let k = !1;
  o === "post" ? r.scheduler = (O) => {
    O.i = h, Ke(O, h && h.suspense);
  } : o !== "sync" && (k = !0, r.scheduler = (O, C) => {
    C ? O() : Hn(O);
  }), r.augmentJob = (O) => {
    t && (O.flags |= 4), k && (O.flags |= 2, h && (O.id = h.uid, O.i = h));
  };
  const R = Lo(e, t, r);
  return gs && (f ? f.push(R) : c && R()), R;
}
function Go(e, t, s) {
  const n = this.proxy, l = me(e) ? e.includes(".") ? vi(n, e) : () => n[e] : e.bind(n, n);
  let o;
  te(t) ? o = t : (o = t.handler, s = t);
  const a = $s(this), r = hi(l, o.bind(n), s);
  return a(), r;
}
function vi(e, t) {
  const s = t.split(".");
  return () => {
    let n = e;
    for (let l = 0; l < s.length && n; l++)
      n = n[s[l]];
    return n;
  };
}
const Yo = /* @__PURE__ */ Symbol("_vte"), Xs = (e) => e.__isTeleport, dn = /* @__PURE__ */ Symbol("_leaveCb");
function Xo(e) {
  let t = e[0];
  if (e.length > 1) {
    for (const s of e)
      if (s.type !== Xe) {
        t = s;
        break;
      }
  }
  return t;
}
function mi(e) {
  if (!Kn(e))
    return Xs(e.type) && e.children ? Xo(e.children) : e;
  if (e.component)
    return e.component.subTree;
  const { shapeFlag: t, children: s } = e;
  if (s) {
    if (t & 16)
      return s[0];
    if (t & 32 && te(s.default))
      return s.default();
  }
}
function js(e, t) {
  if (e.shapeFlag & 6 && e.component) {
    e.transition = t;
    const s = e.component.subTree;
    js(
      Xs(s.type) && mi(s) || s,
      t
    );
  } else if (e.shapeFlag & 128)
    e.ssContent.transition = t.clone(e.ssContent), e.ssFallback.transition = t.clone(e.ssFallback);
  else if (e.transition = t, e.type === V && Q(e.children)) {
    const s = Ci(e.children, !1);
    s && js(s, t);
  }
}
function wn(e) {
  if (e.component)
    return wn(e.component.subTree);
  if (e.type === V) {
    const t = Q(e.children) && Ci(e.children, !1);
    return t ? wn(t) : void 0;
  }
  if (e.type !== Xe)
    return e;
}
function gi(e) {
  e.ids = [e.ids[0] + e.ids[2]++ + "-", 0, 0];
}
function ul(e, t) {
  let s;
  return !!((s = Object.getOwnPropertyDescriptor(e, t)) && !s.configurable);
}
const Ds = /* @__PURE__ */ new WeakMap();
function cs(e, t, s, n, l = !1) {
  if (Q(e)) {
    e.forEach(
      (j, D) => cs(
        j,
        t && (Q(t) ? t[D] : t),
        s,
        n,
        l
      )
    );
    return;
  }
  if (Xt(n) && !l) {
    n.shapeFlag & 512 && n.type.__asyncResolved && n.component.subTree.component && cs(e, t, s, n.component.subTree);
    return;
  }
  const o = n.shapeFlag & 4 ? sn(n.component) : n.el, a = l ? null : o, { i: r, r: c } = e, f = t && t.r, h = r.refs === fe ? r.refs = {} : r.refs, k = r.setupState, R = /* @__PURE__ */ ae(k), O = k === fe ? Fl : (j) => ul(h, j) ? !1 : oe(R, j), C = (j, D) => !(D && ul(h, D));
  if (f != null && f !== c) {
    if (cl(t), me(f))
      h[f] = null, O(f) && (k[f] = null);
    else if (/* @__PURE__ */ De(f)) {
      const j = t;
      C(f, j.k) && (f.value = null), j.k && (h[j.k] = null);
    }
  }
  if (te(c))
    ks(c, r, 12, [a, h]);
  else {
    const j = me(c), D = /* @__PURE__ */ De(c);
    if (j || D) {
      const se = () => {
        if (e.f) {
          const U = j ? O(c) ? k[c] : h[c] : C() || !e.k ? c.value : h[e.k];
          if (l)
            Q(U) && Rn(U, o);
          else if (Q(U))
            U.includes(o) || U.push(o);
          else if (j)
            h[c] = [o], O(c) && (k[c] = h[c]);
          else {
            const L = [o];
            C(c, e.k) && (c.value = L), e.k && (h[e.k] = L);
          }
        } else j ? (h[c] = a, O(c) && (k[c] = a)) : D && (C(c, e.k) && (c.value = a), e.k && (h[e.k] = a));
      };
      if (a) {
        const U = () => {
          se(), Ds.delete(e);
        };
        U.id = -1, Ds.set(e, U), Ke(U, s);
      } else
        cl(e), se();
    }
  }
}
function cl(e) {
  const t = Ds.get(e);
  t && (t.flags |= 8, Ds.delete(e));
}
zs().requestIdleCallback;
zs().cancelIdleCallback;
const Xt = (e) => !!e.type.__asyncLoader, Kn = (e) => e.type.__isKeepAlive;
function Qo(e, t) {
  _i(e, "a", t);
}
function Zo(e, t) {
  _i(e, "da", t);
}
function _i(e, t, s = je) {
  const n = e.__wdc || (e.__wdc = () => {
    let l = s;
    for (; l; ) {
      if (l.isDeactivated)
        return;
      l = l.parent;
    }
    return e();
  });
  if (Qs(t, n, s), s) {
    let l = s.parent;
    for (; l && l.parent; )
      Kn(l.parent.vnode) && er(n, t, s, l), l = l.parent;
  }
}
function er(e, t, s, n) {
  const l = Qs(
    t,
    e,
    n,
    !0
    /* prepend */
  );
  Bn(() => {
    Rn(n[t], l);
  }, s);
}
function Qs(e, t, s = je, n = !1) {
  if (s) {
    const l = s[e] || (s[e] = []), o = t.__weh || (t.__weh = (...a) => {
      _t();
      const r = $s(s), c = it(t, s, e, a);
      return r(), yt(), c;
    });
    return n ? l.unshift(o) : l.push(o), o;
  }
}
const At = (e) => (t, s = je) => {
  (!gs || e === "sp") && Qs(e, (...n) => t(...n), s);
}, tr = At("bm"), Ot = At("m"), sr = At(
  "bu"
), nr = At("u"), lr = At(
  "bum"
), Bn = At("um"), ir = At(
  "sp"
), or = At("rtg"), rr = At("rtc");
function yi(e, t = je) {
  Qs("ec", e, t);
}
const ar = "components", bi = /* @__PURE__ */ Symbol.for("v-ndc");
function ur(e) {
  return me(e) ? cr(ar, e, !1) || e : e || bi;
}
function cr(e, t, s = !0, n = !1) {
  const l = Re || je;
  if (l) {
    const o = l.type;
    {
      const r = Gr(
        o,
        !1
      );
      if (r && (r === t || r === Ve(t) || r === Ws(Ve(t))))
        return o;
    }
    const a = (
      // local registration
      // check instance[type] first which is resolved for options API
      dl(l[e] || o[e], t) || // global registration
      dl(l.appContext[e], t)
    );
    return !a && n ? o : a;
  }
}
function dl(e, t) {
  return e && (e[t] || e[Ve(t)] || e[Ws(Ve(t))]);
}
function ne(e, t, s, n) {
  let l;
  const o = s, a = Q(e);
  if (a || me(e)) {
    const r = a && /* @__PURE__ */ Mt(e);
    let c = !1, f = !1;
    r && (c = !/* @__PURE__ */ Ge(e), f = /* @__PURE__ */ bt(e), e = Gs(e)), l = new Array(e.length);
    for (let h = 0, k = e.length; h < k; h++)
      l[h] = t(
        c ? f ? Dt(Ye(e[h])) : Ye(e[h]) : e[h],
        h,
        void 0,
        o
      );
  } else if (typeof e == "number")
    if (!Number.isInteger(e) || e < 0)
      l = [];
    else {
      l = new Array(e);
      for (let r = 0; r < e; r++)
        l[r] = t(r + 1, r, void 0, o);
    }
  else if (ce(e))
    if (e[Symbol.iterator])
      l = Array.from(
        e,
        (r, c) => t(r, c, void 0, o)
      );
    else {
      const r = Object.keys(e);
      l = new Array(r.length);
      for (let c = 0, f = r.length; c < f; c++) {
        const h = r[c];
        l[c] = t(e[h], h, c, o);
      }
    }
  else
    l = [];
  return l;
}
function dr(e, t, s, n, l, o) {
  if (s == null && (s = {}), Re.ce || Re.parent && Xt(Re.parent) && Re.parent.ce) {
    const f = s, h = Object.keys(f).length > 0;
    return g(), pe(
      V,
      null,
      [gt("slot", f, n)],
      h ? -2 : 64
    );
  }
  let a = e[t];
  a && a._c && (a._d = !1);
  const r = Tt.length;
  g();
  let c;
  try {
    const f = a && ki(a(s)), h = s.key || o || // slot content array of a dynamic conditional slot may have a branch
    // key attached in the `createSlots` helper, respect that
    f && f.key;
    c = pe(
      V,
      {
        key: (h && !lt(h) ? h : `_${t}`) + // #7256 force differentiate fallback content from actual content
        (!f && n ? "_fb" : "")
      },
      f || (n ? n() : []),
      f && e._ === 1 ? 64 : -2
    );
  } catch (f) {
    for (let h = Tt.length; h > r; h--) Jn();
    throw f;
  } finally {
    a && a._c && (a._d = !0);
  }
  return c.scopeId && (c.slotScopeIds = [c.scopeId + "-s"]), c;
}
function ki(e) {
  return e.some((t) => tn(t) ? !(t.type === Xe || t.type === V && !ki(t.children)) : !0) ? e : null;
}
const xn = (e) => e ? Hi(e) ? sn(e) : xn(e.parent) : null, ds = (
  // Move PURE marker to new line to workaround compiler discarding it
  // due to type annotation
  /* @__PURE__ */ Fe(/* @__PURE__ */ Object.create(null), {
    $: (e) => e,
    $el: (e) => e.vnode.el,
    $data: (e) => e.data,
    $props: (e) => e.props,
    $attrs: (e) => e.attrs,
    $slots: (e) => e.slots,
    $refs: (e) => e.refs,
    $parent: (e) => xn(e.parent),
    $root: (e) => xn(e.root),
    $host: (e) => e.ce,
    $emit: (e) => e.emit,
    $options: (e) => wi(e),
    $forceUpdate: (e) => e.f || (e.f = () => {
      Hn(e.update);
    }),
    $nextTick: (e) => e.n || (e.n = Ns.bind(e.proxy)),
    $watch: (e) => Go.bind(e)
  })
), fn = (e, t) => e !== fe && !e.__isScriptSetup && oe(e, t), fr = {
  get({ _: e }, t) {
    if (t === "__v_skip")
      return !0;
    const { ctx: s, setupState: n, data: l, props: o, accessCache: a, type: r, appContext: c } = e;
    if (t[0] !== "$") {
      const R = a[t];
      if (R !== void 0)
        switch (R) {
          case 1:
            return n[t];
          case 2:
            return l[t];
          case 4:
            return s[t];
          case 3:
            return o[t];
        }
      else {
        if (fn(n, t))
          return a[t] = 1, n[t];
        if (l !== fe && oe(l, t))
          return a[t] = 2, l[t];
        if (oe(o, t))
          return a[t] = 3, o[t];
        if (s !== fe && oe(s, t))
          return a[t] = 4, s[t];
        Sn && (a[t] = 0);
      }
    }
    const f = ds[t];
    let h, k;
    if (f)
      return t === "$attrs" && Ne(e.attrs, "get", ""), f(e);
    if (
      // css module (injected by vue-loader)
      (h = r.__cssModules) && (h = h[t])
    )
      return h;
    if (s !== fe && oe(s, t))
      return a[t] = 4, s[t];
    if (
      // global properties
      k = c.config.globalProperties, oe(k, t)
    )
      return k[t];
  },
  set({ _: e }, t, s) {
    const { data: n, setupState: l, ctx: o } = e;
    return fn(l, t) ? (l[t] = s, !0) : n !== fe && oe(n, t) ? (n[t] = s, !0) : oe(e.props, t) || t[0] === "$" && t.slice(1) in e ? !1 : (o[t] = s, !0);
  },
  has({
    _: { data: e, setupState: t, accessCache: s, ctx: n, appContext: l, props: o, type: a }
  }, r) {
    let c;
    return !!(s[r] || e !== fe && r[0] !== "$" && oe(e, r) || fn(t, r) || oe(o, r) || oe(n, r) || oe(ds, r) || oe(l.config.globalProperties, r) || (c = a.__cssModules) && c[r]);
  },
  defineProperty(e, t, s) {
    return s.get != null ? e._.accessCache[t] = 0 : oe(s, "value") && this.set(e, t, s.value, null), Reflect.defineProperty(e, t, s);
  }
};
function fl(e) {
  return Q(e) ? e.reduce(
    (t, s) => (t[s] = null, t),
    {}
  ) : e;
}
let Sn = !0;
function pr(e) {
  const t = wi(e), s = e.proxy, n = e.ctx;
  Sn = !1, t.beforeCreate && pl(t.beforeCreate, e, "bc");
  const {
    // state
    data: l,
    computed: o,
    methods: a,
    watch: r,
    provide: c,
    inject: f,
    // lifecycle
    created: h,
    beforeMount: k,
    mounted: R,
    beforeUpdate: O,
    updated: C,
    activated: j,
    deactivated: D,
    beforeDestroy: se,
    beforeUnmount: U,
    destroyed: L,
    unmounted: I,
    render: X,
    renderTracked: ve,
    renderTriggered: _e,
    errorCaptured: ye,
    serverPrefetch: ot,
    // public API
    expose: we,
    inheritAttrs: Oe,
    // assets
    components: Z,
    directives: q,
    filters: Y
  } = t;
  if (f && hr(f, n, null), a)
    for (const le in a) {
      const re = a[le];
      te(re) && (n[le] = re.bind(s));
    }
  if (l) {
    const le = l.call(s, s);
    ce(le) && (e.data = /* @__PURE__ */ bs(le));
  }
  if (Sn = !0, o)
    for (const le in o) {
      const re = o[le], He = te(re) ? re.bind(s, s) : te(re.get) ? re.get.bind(s, s) : mt, rt = !te(re) && te(re.set) ? re.set.bind(s) : mt, Qe = Ce({
        get: He,
        set: rt
      });
      Object.defineProperty(n, le, {
        enumerable: !0,
        configurable: !0,
        get: () => Qe.value,
        set: (Ee) => Qe.value = Ee
      });
    }
  if (r)
    for (const le in r)
      $i(r[le], n, s, le);
  if (c) {
    const le = te(c) ? c.call(s) : c;
    Reflect.ownKeys(le).forEach((re) => {
      Wo(re, le[re]);
    });
  }
  h && pl(h, e, "c");
  function J(le, re) {
    Q(re) ? re.forEach((He) => le(He.bind(s))) : re && le(re.bind(s));
  }
  if (J(tr, k), J(Ot, R), J(sr, O), J(nr, C), J(Qo, j), J(Zo, D), J(yi, ye), J(rr, ve), J(or, _e), J(lr, U), J(Bn, I), J(ir, ot), Q(we))
    if (we.length) {
      const le = e.exposed || (e.exposed = {});
      we.forEach((re) => {
        Object.defineProperty(le, re, {
          get: () => s[re],
          set: (He) => s[re] = He,
          enumerable: !0
        });
      });
    } else e.exposed || (e.exposed = {});
  X && e.render === mt && (e.render = X), Oe != null && (e.inheritAttrs = Oe), Z && (e.components = Z), q && (e.directives = q), ot && gi(e);
}
function hr(e, t, s = mt) {
  Q(e) && (e = Cn(e));
  for (const n in e) {
    const l = e[n];
    let o;
    ce(l) ? "default" in l ? o = Os(
      l.from || n,
      l.default,
      !0
    ) : o = Os(l.from || n) : o = Os(l), /* @__PURE__ */ De(o) ? Object.defineProperty(t, n, {
      enumerable: !0,
      configurable: !0,
      get: () => o.value,
      set: (a) => o.value = a
    }) : t[n] = o;
  }
}
function pl(e, t, s) {
  it(
    Q(e) ? e.map((n) => n.bind(t.proxy)) : e.bind(t.proxy),
    t,
    s
  );
}
function $i(e, t, s, n) {
  let l = n.includes(".") ? vi(s, n) : () => s[n];
  if (me(e)) {
    const o = t[e];
    te(o) && st(l, o);
  } else if (te(e))
    st(l, e.bind(s));
  else if (ce(e))
    if (Q(e))
      e.forEach((o) => $i(o, t, s, n));
    else {
      const o = te(e.handler) ? e.handler.bind(s) : t[e.handler];
      te(o) && st(l, o, e);
    }
}
function wi(e) {
  const t = e.type, { mixins: s, extends: n } = t, {
    mixins: l,
    optionsCache: o,
    config: { optionMergeStrategies: a }
  } = e.appContext, r = o.get(t);
  let c;
  return r ? c = r : !l.length && !s && !n ? c = t : (c = {}, l.length && l.forEach(
    (f) => Fs(c, f, a, !0)
  ), Fs(c, t, a)), ce(t) && o.set(t, c), c;
}
function Fs(e, t, s, n = !1) {
  const { mixins: l, extends: o } = t;
  o && Fs(e, o, s, !0), l && l.forEach(
    (a) => Fs(e, a, s, !0)
  );
  for (const a in t)
    if (!(n && a === "expose")) {
      const r = vr[a] || s && s[a];
      e[a] = r ? r(e[a], t[a]) : t[a];
    }
  return e;
}
const vr = {
  data: hl,
  props: vl,
  emits: vl,
  // objects
  methods: is,
  computed: is,
  // lifecycle
  beforeCreate: Ue,
  created: Ue,
  beforeMount: Ue,
  mounted: Ue,
  beforeUpdate: Ue,
  updated: Ue,
  beforeDestroy: Ue,
  beforeUnmount: Ue,
  destroyed: Ue,
  unmounted: Ue,
  activated: Ue,
  deactivated: Ue,
  errorCaptured: Ue,
  serverPrefetch: Ue,
  // assets
  components: is,
  directives: is,
  // watch
  watch: gr,
  // provide / inject
  provide: hl,
  inject: mr
};
function hl(e, t) {
  return t ? e ? function() {
    return Fe(
      te(e) ? e.call(this, this) : e,
      te(t) ? t.call(this, this) : t
    );
  } : t : e;
}
function mr(e, t) {
  return is(Cn(e), Cn(t));
}
function Cn(e) {
  if (Q(e)) {
    const t = {};
    for (let s = 0; s < e.length; s++)
      t[e[s]] = e[s];
    return t;
  }
  return e;
}
function Ue(e, t) {
  return e ? [...new Set([].concat(e, t))] : t;
}
function is(e, t) {
  return e ? Fe(/* @__PURE__ */ Object.create(null), e, t) : t;
}
function vl(e, t) {
  return e ? Q(e) && Q(t) ? [.../* @__PURE__ */ new Set([...e, ...t])] : Fe(
    /* @__PURE__ */ Object.create(null),
    fl(e),
    fl(t ?? {})
  ) : t;
}
function gr(e, t) {
  if (!e) return t;
  if (!t) return e;
  const s = Fe(/* @__PURE__ */ Object.create(null), e);
  for (const n in t)
    s[n] = Ue(e[n], t[n]);
  return s;
}
function xi() {
  return {
    app: null,
    config: {
      isNativeTag: Fl,
      performance: !1,
      globalProperties: {},
      optionMergeStrategies: {},
      errorHandler: void 0,
      warnHandler: void 0,
      compilerOptions: {}
    },
    mixins: [],
    components: {},
    directives: {},
    provides: /* @__PURE__ */ Object.create(null),
    optionsCache: /* @__PURE__ */ new WeakMap(),
    propsCache: /* @__PURE__ */ new WeakMap(),
    emitsCache: /* @__PURE__ */ new WeakMap()
  };
}
let _r = 0;
function yr(e, t) {
  return function(n, l = null) {
    te(n) || (n = Fe({}, n)), l != null && !ce(l) && (l = null);
    const o = xi(), a = /* @__PURE__ */ new WeakSet(), r = [];
    let c = !1;
    const f = o.app = {
      _uid: _r++,
      _component: n,
      _props: l,
      _container: null,
      _context: o,
      _instance: null,
      version: Xr,
      get config() {
        return o.config;
      },
      set config(h) {
      },
      use(h, ...k) {
        return a.has(h) || (h && te(h.install) ? (a.add(h), h.install(f, ...k)) : te(h) && (a.add(h), h(f, ...k))), f;
      },
      mixin(h) {
        return o.mixins.includes(h) || o.mixins.push(h), f;
      },
      component(h, k) {
        return k ? (o.components[h] = k, f) : o.components[h];
      },
      directive(h, k) {
        return k ? (o.directives[h] = k, f) : o.directives[h];
      },
      mount(h, k, R) {
        if (!c) {
          const O = f._ceVNode || gt(n, l);
          return O.appContext = o, R === !0 ? R = "svg" : R === !1 && (R = void 0), e(O, h, R), c = !0, f._container = h, h.__vue_app__ = f, sn(O.component);
        }
      },
      onUnmount(h) {
        r.push(h);
      },
      unmount() {
        c && (it(
          r,
          f._instance,
          16
        ), e(null, f._container), delete f._container.__vue_app__);
      },
      provide(h, k) {
        return o.provides[h] = k, f;
      },
      runWithContext(h) {
        const k = Qt;
        Qt = f;
        try {
          return h();
        } finally {
          Qt = k;
        }
      }
    };
    return f;
  };
}
let Qt = null;
const br = (e, t) => t === "modelValue" || t === "model-value" ? e.modelModifiers : e[`${t}Modifiers`] || e[`${Ve(t)}Modifiers`] || e[`${Ft(t)}Modifiers`];
function kr(e, t, ...s) {
  if (e.isUnmounted) return;
  const n = e.vnode.props || fe;
  let l = s;
  const o = t.startsWith("update:"), a = o && br(n, t.slice(7));
  a && (a.trim && (l = s.map((h) => me(h) ? h.trim() : h)), a.number && (l = l.map(Js)));
  let r, c = n[r = ln(t)] || // also try camelCase event handler (#2249)
  n[r = ln(Ve(t))];
  !c && o && (c = n[r = ln(Ft(t))]), c && it(
    c,
    e,
    6,
    l
  );
  const f = n[r + "Once"];
  if (f) {
    if (!e.emitted)
      e.emitted = {};
    else if (e.emitted[r])
      return;
    e.emitted[r] = !0, it(
      f,
      e,
      6,
      l
    );
  }
}
const $r = /* @__PURE__ */ new WeakMap();
function Si(e, t, s = !1) {
  const n = s ? $r : t.emitsCache, l = n.get(e);
  if (l !== void 0)
    return l;
  const o = e.emits;
  let a = {}, r = !1;
  if (!te(e)) {
    const c = (f) => {
      const h = Si(f, t, !0);
      h && (r = !0, Fe(a, h));
    };
    !s && t.mixins.length && t.mixins.forEach(c), e.extends && c(e.extends), e.mixins && e.mixins.forEach(c);
  }
  return !o && !r ? (ce(e) && n.set(e, null), null) : (Q(o) ? o.forEach((c) => a[c] = null) : Fe(a, o), ce(e) && n.set(e, a), a);
}
function Zs(e, t) {
  return !e || !Ks(t) ? !1 : (t = t.slice(2), t = t === "Once" ? t : t.replace(/Once$/, ""), oe(e, t[0].toLowerCase() + t.slice(1)) || oe(e, Ft(t)) || oe(e, t));
}
function ml(e) {
  const {
    type: t,
    vnode: s,
    proxy: n,
    withProxy: l,
    propsOptions: [o],
    slots: a,
    attrs: r,
    emit: c,
    render: f,
    renderCache: h,
    props: k,
    data: R,
    setupState: O,
    ctx: C,
    inheritAttrs: j
  } = e, D = Ms(e);
  let se, U;
  try {
    if (s.shapeFlag & 4) {
      const I = l || n, X = I;
      se = ht(
        f.call(
          X,
          I,
          h,
          k,
          O,
          R,
          C
        )
      ), U = r;
    } else {
      const I = t;
      se = ht(
        I.length > 1 ? I(
          k,
          { attrs: r, slots: a, emit: c }
        ) : I(
          k,
          null
        )
      ), U = t.props ? r : wr(r);
    }
  } catch (I) {
    Tt.length = 0, Ys(I, e, 1), se = gt(Xe);
  }
  let L = se;
  if (U && j !== !1) {
    const I = Object.keys(U), { shapeFlag: X } = L;
    I.length && X & 7 && (o && I.some(Bs) && (U = xr(
      U,
      o
    )), L = Zt(L, U, !1, !0));
  }
  if (s.dirs && (L = Zt(L, null, !1, !0), L.dirs = L.dirs ? L.dirs.concat(s.dirs) : s.dirs), s.transition) {
    const I = Xs(L.type) && mi(L) || L;
    js(I, s.transition);
  }
  return se = L, Ms(D), se;
}
function Ci(e, t = !0) {
  let s;
  for (let n = 0; n < e.length; n++) {
    const l = e[n];
    if (tn(l)) {
      if (l.type !== Xe || l.children === "v-if") {
        if (s)
          return;
        s = l;
      }
    } else
      return;
  }
  return s;
}
const wr = (e) => {
  let t;
  for (const s in e)
    (s === "class" || s === "style" || Ks(s)) && ((t || (t = {}))[s] = e[s]);
  return t;
}, xr = (e, t) => {
  const s = {};
  for (const n in e)
    (!Bs(n) || !(n.slice(9) in t)) && (s[n] = e[n]);
  return s;
};
function Sr(e, t, s) {
  const { props: n, children: l, component: o } = e, { props: a, children: r, patchFlag: c } = t, f = o.emitsOptions;
  if (t.dirs || t.transition)
    return !0;
  if (s && c >= 0) {
    if (c & 1024)
      return !0;
    if (c & 16)
      return n ? gl(n, a, f) : !!a;
    if (c & 8) {
      const h = t.dynamicProps;
      for (let k = 0; k < h.length; k++) {
        const R = h[k];
        if (Ti(a, n, R) && !Zs(f, R))
          return !0;
      }
    }
  } else
    return (l || r) && (!r || !r.$stable) ? !0 : n === a ? !1 : n ? a ? gl(n, a, f) : !0 : !!a;
  return !1;
}
function gl(e, t, s) {
  const n = Object.keys(t);
  if (n.length !== Object.keys(e).length)
    return !0;
  for (let l = 0; l < n.length; l++) {
    const o = n[l];
    if (!oe(e, o) || Ti(t, e, o) && !Zs(s, o))
      return !0;
  }
  return !1;
}
function Ti(e, t, s) {
  const n = e[s], l = t[s];
  return s === "style" && ce(n) && ce(l) ? !jt(n, l) : n !== l;
}
function Cr({ vnode: e, parent: t, suspense: s }, n) {
  for (; t; ) {
    const l = t.subTree;
    if (l.suspense && l.suspense.activeBranch === e && (l.suspense.vnode.el = l.el = n, e = l), l === e)
      (e = t.vnode).el = n, t = t.parent;
    else
      break;
  }
  s && s.activeBranch === e && (s.vnode.el = n);
}
const Ai = {}, Oi = () => Object.create(Ai), Ei = (e) => Object.getPrototypeOf(e) === Ai;
function Tr(e, t, s, n = !1) {
  const l = {}, o = Oi();
  e.propsDefaults = /* @__PURE__ */ Object.create(null), Pi(e, t, l, o);
  for (const a in e.propsOptions[0])
    a in l || (l[a] = void 0);
  s ? e.props = n ? l : /* @__PURE__ */ Io(l) : e.type.props ? e.props = l : e.props = o, e.attrs = o;
}
function Ar(e, t, s, n) {
  const {
    props: l,
    attrs: o,
    vnode: { patchFlag: a }
  } = e, r = /* @__PURE__ */ ae(l), [c] = e.propsOptions;
  let f = !1;
  if (
    // always force full diff in dev
    // - #1942 if hmr is enabled with sfc component
    // - vite#872 non-sfc component used by sfc component
    (n || a > 0) && !(a & 16)
  ) {
    if (a & 8) {
      const h = e.vnode.dynamicProps;
      for (let k = 0; k < h.length; k++) {
        let R = h[k];
        if (Zs(e.emitsOptions, R))
          continue;
        const O = t[R];
        if (c)
          if (oe(o, R))
            O !== o[R] && (o[R] = O, f = !0);
          else {
            const C = Ve(R);
            l[C] = Tn(
              c,
              r,
              C,
              O,
              e,
              !1
            );
          }
        else
          O !== o[R] && (o[R] = O, f = !0);
      }
    }
  } else {
    Pi(e, t, l, o) && (f = !0);
    let h;
    for (const k in r)
      (!t || // for camelCase
      !oe(t, k) && // it's possible the original props was passed in as kebab-case
      // and converted to camelCase (#955)
      ((h = Ft(k)) === k || !oe(t, h))) && (c ? s && // for camelCase
      (s[k] !== void 0 || // for kebab-case
      s[h] !== void 0) && (l[k] = Tn(
        c,
        r,
        k,
        void 0,
        e,
        !0
      )) : delete l[k]);
    if (o !== r)
      for (const k in o)
        (!t || !oe(t, k)) && (delete o[k], f = !0);
  }
  f && St(e.attrs, "set", "");
}
function Pi(e, t, s, n) {
  const [l, o] = e.propsOptions;
  let a = !1, r;
  if (t)
    for (let c in t) {
      if (rs(c))
        continue;
      const f = t[c];
      let h;
      l && oe(l, h = Ve(c)) ? !o || !o.includes(h) ? s[h] = f : (r || (r = {}))[h] = f : Zs(e.emitsOptions, c) || (!(c in n) || f !== n[c]) && (n[c] = f, a = !0);
    }
  if (o) {
    const c = /* @__PURE__ */ ae(s), f = r || fe;
    for (let h = 0; h < o.length; h++) {
      const k = o[h];
      s[k] = Tn(
        l,
        c,
        k,
        f[k],
        e,
        !oe(f, k)
      );
    }
  }
  return a;
}
function Tn(e, t, s, n, l, o) {
  const a = e[s];
  if (a != null) {
    const r = oe(a, "default");
    if (r && n === void 0) {
      const c = a.default;
      if (a.type !== Function && !a.skipFactory && te(c)) {
        const { propsDefaults: f } = l;
        if (s in f)
          n = f[s];
        else {
          const h = $s(l);
          n = f[s] = c.call(
            null,
            t
          ), h();
        }
      } else
        n = c;
      l.ce && l.ce._setProp(s, n);
    }
    a[
      0
      /* shouldCast */
    ] && (o && !r ? n = !1 : a[
      1
      /* shouldCastTrue */
    ] && (n === "" || n === Ft(s)) && (n = !0));
  }
  return n;
}
const Or = /* @__PURE__ */ new WeakMap();
function Ii(e, t, s = !1) {
  const n = s ? Or : t.propsCache, l = n.get(e);
  if (l)
    return l;
  const o = e.props, a = {}, r = [];
  let c = !1;
  if (!te(e)) {
    const h = (k) => {
      c = !0;
      const [R, O] = Ii(k, t, !0);
      Fe(a, R), O && r.push(...O);
    };
    !s && t.mixins.length && t.mixins.forEach(h), e.extends && h(e.extends), e.mixins && e.mixins.forEach(h);
  }
  if (!o && !c)
    return ce(e) && n.set(e, Kt), Kt;
  if (Q(o))
    for (let h = 0; h < o.length; h++) {
      const k = Ve(o[h]);
      _l(k) && (a[k] = fe);
    }
  else if (o)
    for (const h in o) {
      const k = Ve(h);
      if (_l(k)) {
        const R = o[h], O = a[k] = Q(R) || te(R) ? { type: R } : Fe({}, R), C = O.type;
        let j = !1, D = !0;
        if (Q(C))
          for (let se = 0; se < C.length; ++se) {
            const U = C[se], L = te(U) && U.name;
            if (L === "Boolean") {
              j = !0;
              break;
            } else L === "String" && (D = !1);
          }
        else
          j = te(C) && C.name === "Boolean";
        O[
          0
          /* shouldCast */
        ] = j, O[
          1
          /* shouldCastTrue */
        ] = D, (j || oe(O, "default")) && r.push(k);
      }
    }
  const f = [a, r];
  return ce(e) && n.set(e, f), f;
}
function _l(e) {
  return e[0] !== "$" && !rs(e);
}
const qn = (e) => e === "_" || e === "_ctx" || e === "$stable", Wn = (e) => Q(e) ? e.map(ht) : [ht(e)], Er = (e, t, s) => {
  if (t._n)
    return t;
  const n = qo((...l) => Wn(t(...l)), s);
  return n._c = !1, n;
}, Ri = (e, t, s) => {
  const n = e._ctx;
  for (const l in e) {
    if (qn(l)) continue;
    const o = e[l];
    if (te(o))
      t[l] = Er(l, o, n);
    else if (o != null) {
      const a = Wn(o);
      t[l] = () => a;
    }
  }
}, Ni = (e, t) => {
  const s = Wn(t);
  e.slots.default = () => s;
}, Mi = (e, t, s) => {
  for (const n in t)
    (s || !qn(n)) && (e[n] = t[n]);
}, Pr = (e, t, s) => {
  const n = e.slots = Oi();
  if (e.vnode.shapeFlag & 32) {
    const l = t._;
    l ? (Mi(n, t, s), s && Hl(n, "_", l, !0)) : Ri(t, n);
  } else t && Ni(e, t);
}, Ir = (e, t, s) => {
  const { vnode: n, slots: l } = e;
  let o = !0, a = fe;
  if (n.shapeFlag & 32) {
    const r = t._;
    r ? s && r === 1 ? o = !1 : Mi(l, t, s) : (o = !t.$stable, Ri(t, l)), a = t;
  } else t && (Ni(e, t), a = { default: 1 });
  if (o)
    for (const r in l)
      !qn(r) && a[r] == null && delete l[r];
}, Ke = Dr;
function Rr(e) {
  return Nr(e);
}
function Nr(e, t) {
  const s = zs();
  s.__VUE__ = !0;
  const {
    insert: n,
    remove: l,
    patchProp: o,
    createElement: a,
    createText: r,
    createComment: c,
    setText: f,
    setElementText: h,
    parentNode: k,
    nextSibling: R,
    setScopeId: O = mt,
    insertStaticContent: C
  } = e, j = (u, m, $, E = null, x = null, T = null, M = void 0, v = null, p = !!m.dynamicChildren) => {
    if (u === m)
      return;
    u && !ns(u, m) && (E = Et(u), Ee(u, x, T, !0), u = null), m.patchFlag === -2 && (p = !1, m.dynamicChildren = null), m.dynamicChildren && u && u.dynamicChildren && u.dynamicChildren.hasOnce && (m.dynamicChildren === Kt && (m.dynamicChildren = []), m.dynamicChildren.hasOnce = !0);
    const { type: d, ref: P, shapeFlag: S } = m;
    switch (d) {
      case en:
        D(u, m, $, E);
        break;
      case Xe:
        se(u, m, $, E);
        break;
      case hn:
        u == null && U(m, $, E, M);
        break;
      case V:
        Z(
          u,
          m,
          $,
          E,
          x,
          T,
          M,
          v,
          p
        );
        break;
      default:
        S & 1 ? X(
          u,
          m,
          $,
          E,
          x,
          T,
          M,
          v,
          p
        ) : S & 6 ? q(
          u,
          m,
          $,
          E,
          x,
          T,
          M,
          v,
          p
        ) : (S & 64 || S & 128) && d.process(
          u,
          m,
          $,
          E,
          x,
          T,
          M,
          v,
          p,
          b
        );
    }
    P != null && x ? cs(P, u && u.ref, T, m || u, !m) : P == null && u && u.ref != null && cs(u.ref, null, T, u, !0);
  }, D = (u, m, $, E) => {
    if (u == null)
      n(
        m.el = r(m.children),
        $,
        E
      );
    else {
      const x = m.el = u.el;
      m.children !== u.children && f(x, m.children);
    }
  }, se = (u, m, $, E) => {
    u == null ? n(
      m.el = c(m.children || ""),
      $,
      E
    ) : m.el = u.el;
  }, U = (u, m, $, E) => {
    [u.el, u.anchor] = C(
      u.children,
      m,
      $,
      E,
      u.el,
      u.anchor
    );
  }, L = ({ el: u, anchor: m }, $, E) => {
    let x;
    for (; u && u !== m; )
      x = R(u), n(u, $, E), u = x;
    n(m, $, E);
  }, I = ({ el: u, anchor: m }) => {
    let $;
    for (; u && u !== m; )
      $ = R(u), l(u), u = $;
    l(m);
  }, X = (u, m, $, E, x, T, M, v, p) => {
    if (m.type === "svg" ? M = "svg" : m.type === "math" && (M = "mathml"), u == null)
      ve(
        m,
        $,
        E,
        x,
        T,
        M,
        v,
        p
      );
    else {
      const d = u.el && u.el._isVueCE ? u.el : null;
      try {
        d && d._beginPatch(), ot(
          u,
          m,
          x,
          T,
          M,
          v,
          p
        );
      } finally {
        d && d._endPatch();
      }
    }
  }, ve = (u, m, $, E, x, T, M, v) => {
    let p, d;
    const { props: P, shapeFlag: S, transition: A, dirs: B } = u;
    if (p = u.el = a(
      u.type,
      T,
      P && P.is,
      P
    ), S & 8 ? h(p, u.children) : S & 16 && ye(
      u.children,
      p,
      null,
      E,
      x,
      pn(u, T),
      M,
      v
    ), B && Ut(u, null, E, "created"), _e(p, u, u.scopeId, M, E), P) {
      for (const de in P)
        de !== "value" && !rs(de) && o(p, de, null, P[de], T, E);
      "value" in P && o(p, "value", null, P.value, T), (d = P.onVnodeBeforeMount) && dt(d, E, u);
    }
    B && Ut(u, null, E, "beforeMount");
    const K = Mr(x, A);
    K && A.beforeEnter(p), n(p, m, $), ((d = P && P.onVnodeMounted) || K || B) && Ke(() => {
      try {
        d && dt(d, E, u), K && A.enter(p), B && Ut(u, null, E, "mounted");
      } finally {
      }
    }, x);
  }, _e = (u, m, $, E, x) => {
    if ($ && O(u, $), E)
      for (let T = 0; T < E.length; T++)
        O(u, E[T]);
    if (x) {
      let T = x.subTree;
      if (m === T || Fi(T.type) && (T.ssContent === m || T.ssFallback === m)) {
        const M = x.vnode;
        _e(
          u,
          M,
          M.scopeId,
          M.slotScopeIds,
          x.parent
        );
      }
    }
  }, ye = (u, m, $, E, x, T, M, v, p = 0) => {
    for (let d = p; d < u.length; d++) {
      const P = u[d] = v ? xt(u[d]) : ht(u[d]);
      j(
        null,
        P,
        m,
        $,
        E,
        x,
        T,
        M,
        v
      );
    }
  }, ot = (u, m, $, E, x, T, M) => {
    const v = m.el = u.el;
    let { patchFlag: p, dynamicChildren: d, dirs: P } = m;
    p |= u.patchFlag & 16;
    const S = u.props || fe, A = m.props || fe;
    let B;
    if ($ && Lt($, !1), (B = A.onVnodeBeforeUpdate) && dt(B, $, m, u), P && Ut(m, u, $, "beforeUpdate"), $ && Lt($, !0), // #6385 the old vnode may be a user-wrapped non-isomorphic block
    // Force full diff when block metadata is unstable.
    d && (!u.dynamicChildren || u.dynamicChildren.length !== d.length) && (p = 0, M = !1, d = null), (S.innerHTML && A.innerHTML == null || S.textContent && A.textContent == null) && h(v, ""), d ? we(
      u.dynamicChildren,
      d,
      v,
      $,
      E,
      pn(m, x),
      T
    ) : M || re(
      u,
      m,
      v,
      null,
      $,
      E,
      pn(m, x),
      T,
      !1
    ), p > 0) {
      if (p & 16)
        Oe(v, S, A, $, x);
      else if (p & 2 && S.class !== A.class && o(v, "class", null, A.class, x), p & 4 && o(v, "style", S.style, A.style, x), p & 8) {
        const K = m.dynamicProps;
        for (let de = 0; de < K.length; de++) {
          const ue = K[de], Se = S[ue], Pe = A[ue];
          (Pe !== Se || ue === "value") && o(v, ue, Se, Pe, x, $);
        }
      }
      p & 1 && u.children !== m.children && h(v, m.children);
    } else !M && d == null && Oe(v, S, A, $, x);
    ((B = A.onVnodeUpdated) || P) && Ke(() => {
      B && dt(B, $, m, u), P && Ut(m, u, $, "updated");
    }, E);
  }, we = (u, m, $, E, x, T, M) => {
    for (let v = 0; v < m.length; v++) {
      const p = u[v], d = m[v], P = p.el || An(p), S = (
        // oldVNode may be an errored async setup() component inside Suspense
        // which will not have a mounted element
        P && // - In the case of a Fragment, we need to provide the actual parent
        // of the Fragment itself so it can move its children.
        (p.type === V || // - In the case of different nodes, there is going to be a replacement
        // which also requires the correct parent container
        !ns(p, d) || // - In the case of a component, it could contain anything.
        p.shapeFlag & 198) ? k(P) : (
          // In other cases, the parent container is not actually used so we
          // just pass the block element here to avoid a DOM parentNode call.
          $
        )
      );
      j(
        p,
        d,
        S,
        null,
        E,
        x,
        T,
        M,
        !0
      );
    }
  }, Oe = (u, m, $, E, x) => {
    if (m !== $) {
      if (m !== fe)
        for (const T in m)
          !rs(T) && !(T in $) && o(
            u,
            T,
            m[T],
            null,
            x,
            E
          );
      for (const T in $) {
        if (rs(T)) continue;
        const M = $[T], v = m[T];
        M !== v && T !== "value" && o(u, T, v, M, x, E);
      }
      "value" in $ && o(u, "value", m.value, $.value, x);
    }
  }, Z = (u, m, $, E, x, T, M, v, p) => {
    const d = m.el = u ? u.el : r(""), P = m.anchor = u ? u.anchor : r("");
    let { patchFlag: S, dynamicChildren: A, slotScopeIds: B } = m;
    B && (v = v ? v.concat(B) : B), u == null ? (n(d, $, E), n(P, $, E), ye(
      // #10007
      // such fragment like `<></>` will be compiled into
      // a fragment which doesn't have a children.
      // In this case fallback to an empty array
      m.children || [],
      $,
      P,
      x,
      T,
      M,
      v,
      p
    )) : S > 0 && S & 64 && A && // #2715 the previous fragment could've been a BAILed one as a result
    // of renderSlot() with no valid children
    u.dynamicChildren && u.dynamicChildren.length === A.length ? (we(
      u.dynamicChildren,
      A,
      $,
      x,
      T,
      M,
      v
    ), // #2080 if the stable fragment has a key, it's a <template v-for> that may
    //  get moved around. Make sure all root level vnodes inherit el.
    // #2134 or if it's a component root, it may also get moved around
    // as the component is being moved.
    (m.key != null || x && m === x.subTree) && ji(
      u,
      m,
      !0
      /* shallow */
    )) : re(
      u,
      m,
      $,
      P,
      x,
      T,
      M,
      v,
      p
    );
  }, q = (u, m, $, E, x, T, M, v, p) => {
    m.slotScopeIds = v, u == null ? m.shapeFlag & 512 ? x.ctx.activate(
      m,
      $,
      E,
      M,
      p
    ) : Y(
      m,
      $,
      E,
      x,
      T,
      M,
      p
    ) : xe(u, m, p);
  }, Y = (u, m, $, E, x, T, M) => {
    const v = u.component = Kr(
      u,
      E,
      x
    );
    if (Kn(u) && (v.ctx.renderer = b), qr(v, !1, M), v.asyncDep) {
      if (x && x.registerDep(
        v,
        J,
        M,
        T
      ), !u.el) {
        const p = v.subTree = gt(Xe);
        se(null, p, m, $), u.placeholder = p.el;
      }
    } else
      J(
        v,
        u,
        m,
        $,
        x,
        T,
        M
      );
  }, xe = (u, m, $) => {
    const E = m.component = u.component;
    if (Sr(u, m, $))
      if (E.asyncDep && !E.asyncResolved) {
        m.el = u.el, m.placeholder = u.placeholder, le(E, m, $);
        return;
      } else
        E.next = m, E.update();
    else
      m.el = u.el, m.placeholder = u.placeholder, E.vnode = m;
  }, J = (u, m, $, E, x, T, M) => {
    const v = () => {
      if (u.isMounted) {
        let { next: S, bu: A, u: B, parent: K, vnode: de } = u;
        {
          const ut = Di(u);
          if (ut) {
            S && (S.el = de.el, le(u, S, M)), ut.asyncDep.then(() => {
              Ke(() => {
                u.isUnmounted || d();
              }, x);
            });
            return;
          }
        }
        let ue = S, Se;
        Lt(u, !1), S ? (S.el = de.el, le(u, S, M)) : S = de, A && As(A), (Se = S.props && S.props.onVnodeBeforeUpdate) && dt(Se, K, S, de), Lt(u, !0);
        const Pe = ml(u), at = u.subTree;
        u.subTree = Pe, j(
          at,
          Pe,
          // parent may have changed if it's in a teleport
          k(at.el),
          // anchor may have changed if it's in a fragment
          Et(at),
          u,
          x,
          T
        ), S.el = Pe.el, ue === null && Cr(u, Pe.el), B && Ke(B, x), (Se = S.props && S.props.onVnodeUpdated) && Ke(
          () => dt(Se, K, S, de),
          x
        );
      } else {
        let S;
        const { el: A, props: B } = m, { bm: K, m: de, parent: ue, root: Se, type: Pe } = u, at = Xt(m);
        Lt(u, !1), K && As(K), !at && (S = B && B.onVnodeBeforeMount) && dt(S, ue, m), Lt(u, !0);
        {
          Se.ce && Se.ce._hasShadowRoot() && Se.ce._injectChildStyle(
            Pe,
            u.parent ? u.parent.type : void 0
          );
          const ut = u.subTree = ml(u);
          j(
            null,
            ut,
            $,
            E,
            u,
            x,
            T
          ), m.el = ut.el;
        }
        if (de && Ke(de, x), !at && (S = B && B.onVnodeMounted)) {
          const ut = m;
          Ke(
            () => dt(S, ue, ut),
            x
          );
        }
        (m.shapeFlag & 256 || ue && Xt(ue.vnode) && ue.vnode.shapeFlag & 256) && u.a && Ke(u.a, x), u.isMounted = !0, m = $ = E = null;
      }
    };
    u.scope.on();
    const p = u.effect = new Wl(v);
    u.scope.off();
    const d = u.update = p.run.bind(p), P = u.job = p.runIfDirty.bind(p);
    P.i = u, P.id = u.uid, p.scheduler = () => Hn(P), Lt(u, !0), d();
  }, le = (u, m, $) => {
    m.component = u;
    const E = u.vnode.props;
    u.vnode = m, u.next = null, Ar(u, m.props, E, $), Ir(u, m.children, $), _t(), ci(u), yt();
  }, re = (u, m, $, E, x, T, M, v, p = !1) => {
    const d = u && u.children, P = u ? u.shapeFlag : 0, S = m.children, { patchFlag: A, shapeFlag: B } = m;
    if (A > 0) {
      if (A & 128) {
        rt(
          d,
          S,
          $,
          E,
          x,
          T,
          M,
          v,
          p
        );
        return;
      } else if (A & 256) {
        He(
          d,
          S,
          $,
          E,
          x,
          T,
          M,
          v,
          p
        );
        return;
      }
    }
    B & 8 ? (P & 16 && Ze(d, x, T), S !== d && h($, S)) : P & 16 ? B & 16 ? rt(
      d,
      S,
      $,
      E,
      x,
      T,
      M,
      v,
      p
    ) : Ze(d, x, T, !0) : (P & 8 && h($, ""), B & 16 && ye(
      S,
      $,
      E,
      x,
      T,
      M,
      v,
      p
    ));
  }, He = (u, m, $, E, x, T, M, v, p) => {
    u = u || Kt, m = m || Kt;
    const d = u.length, P = m.length, S = Math.min(d, P);
    let A;
    for (A = 0; A < S; A++) {
      const B = m[A] = p ? xt(m[A]) : ht(m[A]);
      j(
        u[A],
        B,
        $,
        null,
        x,
        T,
        M,
        v,
        p
      );
    }
    d > P ? Ze(
      u,
      x,
      T,
      !0,
      !1,
      S
    ) : ye(
      m,
      $,
      E,
      x,
      T,
      M,
      v,
      p,
      S
    );
  }, rt = (u, m, $, E, x, T, M, v, p) => {
    let d = 0;
    const P = m.length;
    let S = u.length - 1, A = P - 1;
    for (; d <= S && d <= A; ) {
      const B = u[d], K = m[d] = p ? xt(m[d]) : ht(m[d]);
      if (ns(B, K))
        j(
          B,
          K,
          $,
          null,
          x,
          T,
          M,
          v,
          p
        );
      else
        break;
      d++;
    }
    for (; d <= S && d <= A; ) {
      const B = u[S], K = m[A] = p ? xt(m[A]) : ht(m[A]);
      if (ns(B, K))
        j(
          B,
          K,
          $,
          null,
          x,
          T,
          M,
          v,
          p
        );
      else
        break;
      S--, A--;
    }
    if (d > S) {
      if (d <= A) {
        const B = A + 1, K = B < P ? m[B].el : E;
        for (; d <= A; )
          j(
            null,
            m[d] = p ? xt(m[d]) : ht(m[d]),
            $,
            K,
            x,
            T,
            M,
            v,
            p
          ), d++;
      }
    } else if (d > A)
      for (; d <= S; )
        Ee(u[d], x, T, !0), d++;
    else {
      const B = d, K = d, de = /* @__PURE__ */ new Map();
      for (d = K; d <= A; d++) {
        const qe = m[d] = p ? xt(m[d]) : ht(m[d]);
        qe.key != null && de.set(qe.key, d);
      }
      let ue, Se = 0;
      const Pe = A - K + 1;
      let at = !1, ut = 0;
      const ts = new Array(Pe);
      for (d = 0; d < Pe; d++) ts[d] = 0;
      for (d = B; d <= S; d++) {
        const qe = u[d];
        if (Se >= Pe) {
          Ee(qe, x, T, !0);
          continue;
        }
        let ct;
        if (qe.key != null)
          ct = de.get(qe.key);
        else
          for (ue = K; ue <= A; ue++)
            if (ts[ue - K] === 0 && ns(qe, m[ue])) {
              ct = ue;
              break;
            }
        ct === void 0 ? Ee(qe, x, T, !0) : (ts[ct - K] = d + 1, ct >= ut ? ut = ct : at = !0, j(
          qe,
          m[ct],
          $,
          null,
          x,
          T,
          M,
          v,
          p
        ), Se++);
      }
      const Xn = at ? jr(ts) : Kt;
      for (ue = Xn.length - 1, d = Pe - 1; d >= 0; d--) {
        const qe = K + d, ct = m[qe], Qn = m[qe + 1], Zn = qe + 1 < P ? (
          // #13559, #14173 fallback to el placeholder for unresolved async component
          Qn.el || An(Qn)
        ) : E;
        ts[d] === 0 ? j(
          null,
          ct,
          $,
          Zn,
          x,
          T,
          M,
          v,
          p
        ) : at && (ue < 0 || d !== Xn[ue] ? Qe(ct, $, Zn, 2) : ue--);
      }
    }
  }, Qe = (u, m, $, E, x = null) => {
    const { el: T, type: M, transition: v, children: p, shapeFlag: d } = u;
    if (d & 6) {
      Qe(u.component.subTree, m, $, E);
      return;
    }
    if (d & 128) {
      u.suspense.move(m, $, E);
      return;
    }
    if (d & 64) {
      M.move(u, m, $, b);
      return;
    }
    if (M === V) {
      n(T, m, $);
      for (let S = 0; S < p.length; S++)
        Qe(p[S], m, $, E);
      n(u.anchor, m, $);
      return;
    }
    if (M === hn) {
      L(u, m, $);
      return;
    }
    if (E !== 2 && d & 1 && v)
      if (E === 0)
        v.persisted && !T[dn] ? n(T, m, $) : (v.beforeEnter(T), n(T, m, $), Ke(() => v.enter(T), x));
      else {
        const { leave: S, delayLeave: A, afterLeave: B } = v, K = () => {
          u.ctx.isUnmounted ? l(T) : n(T, m, $);
        }, de = () => {
          const ue = T._isLeaving || !!T[dn];
          T._isLeaving && T[dn](
            !0
            /* cancelled */
          ), v.persisted && !ue ? K() : S(T, () => {
            K(), B && B();
          });
        };
        A ? A(T, K, de) : de();
      }
    else
      n(T, m, $);
  }, Ee = (u, m, $, E = !1, x = !1) => {
    const {
      type: T,
      props: M,
      ref: v,
      children: p,
      dynamicChildren: d,
      shapeFlag: P,
      patchFlag: S,
      dirs: A,
      cacheIndex: B,
      memo: K
    } = u;
    if ((S === -2 || d && d.hasOnce) && (x = !1), v != null && (_t(), cs(v, null, $, u, !0), yt()), B != null && (!u.ctx || u.ctx === m) && (m.renderCache[B] = void 0), P & 256) {
      m.ctx.deactivate(u);
      return;
    }
    const de = P & 1 && A, ue = !Xt(u);
    let Se;
    if (ue && (Se = M && M.onVnodeBeforeUnmount) && dt(Se, m, u), P & 6)
      Je(u.component, $, E);
    else {
      if (P & 128) {
        u.suspense.unmount($, E);
        return;
      }
      de && Ut(u, null, m, "beforeUnmount"), P & 64 ? u.type.remove(
        u,
        m,
        $,
        b,
        E
      ) : d && // #5154
      // when v-once is used inside a block, setBlockTracking(-1) marks the
      // parent block with hasOnce: true
      // so that it doesn't take the fast path during unmount - otherwise
      // components nested in v-once are never unmounted.
      !d.hasOnce && // #1153: fast path should not be taken for non-stable (v-for) fragments
      (T !== V || S > 0 && S & 64) ? Ze(
        d,
        m,
        $,
        !1,
        !0
      ) : (T === V && S & 384 || !x && P & 16) && Ze(p, m, $), E && zt(u);
    }
    const Pe = K != null && B == null;
    (ue && (Se = M && M.onVnodeUnmounted) || de || Pe) && Ke(() => {
      Se && dt(Se, m, u), de && Ut(u, null, m, "unmounted"), Pe && (u.el = null);
    }, $);
  }, zt = (u) => {
    const { type: m, el: $, anchor: E, transition: x } = u, T = m === V;
    if (T && !x) {
      N($, E);
      return;
    }
    if (m === hn) {
      I(u), x && !x.persisted && x.afterLeave && x.afterLeave();
      return;
    }
    const M = T ? wn(u) : u, v = () => {
      T ? k($) && N($, E) : l($), x && !x.persisted && x.afterLeave && x.afterLeave();
    };
    if (M && M.shapeFlag & 1 && x && !x.persisted) {
      const { leave: p, delayLeave: d } = x, P = M.el, S = () => p(P, v);
      d ? d(P, v, S) : S();
    } else
      v();
  }, N = (u, m) => {
    let $;
    for (; u !== m; )
      $ = R(u), l(u), u = $;
    l(m);
  }, Je = (u, m, $) => {
    const { bum: E, scope: x, job: T, subTree: M, um: v, m: p, a: d } = u;
    yl(p), yl(d), E && As(E), x.stop(), T ? (T.flags |= 8, Ee(M, u, m, $)) : u.vnode.el && M && (M.transition = u.vnode.transition, Ee(M, u, m, $)), v && Ke(v, m), Ke(() => {
      u.isUnmounted = !0;
    }, m);
  }, Ze = (u, m, $, E = !1, x = !1, T = 0) => {
    for (let M = T; M < u.length; M++)
      Ee(u[M], m, $, E, x);
  }, Et = (u) => {
    if (u.shapeFlag & 6)
      return Et(u.component.subTree);
    if (u.shapeFlag & 128)
      return u.suspense.next();
    const m = R(u.anchor || u.el), $ = m && m[Yo];
    return $ ? R($) : m;
  }, w = (u, m, $) => {
    const E = u && m._vnode ? void 0 : u && u.component ? u.component.uid : Hr();
    Bo(() => {
      u == null ? m._vnode && Ee(m._vnode, null, null, !0) : j(
        m._vnode || null,
        u,
        m,
        null,
        null,
        null,
        $
      ), m._vnode = u;
    }, E);
  }, b = {
    p: j,
    um: Ee,
    m: Qe,
    r: zt,
    mt: Y,
    mc: ye,
    pc: re,
    pbc: we,
    n: Et,
    o: e
  };
  return {
    render: w,
    hydrate: void 0,
    createApp: yr(w)
  };
}
function pn({ type: e, props: t }, s) {
  return s === "svg" && e === "foreignObject" || s === "mathml" && e === "annotation-xml" && t && t.encoding && t.encoding.includes("html") ? void 0 : s;
}
function Lt({ effect: e, job: t }, s) {
  s ? (e.flags |= 32, t.flags |= 4) : (e.flags &= -33, t.flags &= -5);
}
function Mr(e, t) {
  return (!e || e && !e.pendingBranch) && t && !t.persisted;
}
function ji(e, t, s = !1) {
  const n = e.children, l = t.children;
  if (Q(n) && Q(l))
    for (let o = 0; o < n.length; o++) {
      const a = n[o];
      let r = l[o];
      r.shapeFlag & 1 && !r.dynamicChildren && ((r.patchFlag <= 0 || r.patchFlag === 32) && (r = l[o] = xt(l[o]), r.el = a.el), !s && r.patchFlag !== -2 && ji(a, r)), r.type === en && (r.patchFlag === -1 && (r = l[o] = xt(r)), r.el = a.el), r.type === Xe && !r.el && (r.el = a.el);
    }
}
function jr(e) {
  const t = e.slice(), s = [0];
  let n, l, o, a, r;
  const c = e.length;
  for (n = 0; n < c; n++) {
    const f = e[n];
    if (f !== 0) {
      if (l = s[s.length - 1], e[l] < f) {
        t[n] = l, s.push(n);
        continue;
      }
      for (o = 0, a = s.length - 1; o < a; )
        r = o + a >> 1, e[s[r]] < f ? o = r + 1 : a = r;
      f < e[s[o]] && (o > 0 && (t[n] = s[o - 1]), s[o] = n);
    }
  }
  for (o = s.length, a = s[o - 1]; o-- > 0; )
    s[o] = a, a = t[a];
  return s;
}
function Di(e) {
  const t = e.subTree.component;
  if (t)
    return t.asyncDep && !t.asyncResolved ? t : Di(t);
}
function yl(e) {
  if (e)
    for (let t = 0; t < e.length; t++)
      e[t].flags |= 8;
}
function An(e) {
  if (e.placeholder)
    return e.placeholder;
  const t = e.component;
  return t ? An(t.subTree) : null;
}
const Fi = (e) => e.__isSuspense;
function Dr(e, t) {
  t && t.pendingBranch ? Q(e) ? t.effects.push(...e) : t.effects.push(e) : Ko(e);
}
const V = /* @__PURE__ */ Symbol.for("v-fgt"), en = /* @__PURE__ */ Symbol.for("v-txt"), Xe = /* @__PURE__ */ Symbol.for("v-cmt"), hn = /* @__PURE__ */ Symbol.for("v-stc"), Tt = [];
let We = null;
function g(e = !1) {
  Tt.push(We = e ? null : []);
}
function Jn() {
  Tt.pop(), We = Tt[Tt.length - 1] || null;
}
let vs = 1;
function bl(e, t = !1) {
  vs += e, e < 0 && We && t && (We.hasOnce = !0);
}
function Ui(e) {
  return e.dynamicChildren = vs > 0 ? We || Kt : null, Jn(), vs > 0 && We && We.push(e), e;
}
function y(e, t, s, n, l, o) {
  return Ui(
    i(
      e,
      t,
      s,
      n,
      l,
      o,
      !0
    )
  );
}
function pe(e, t, s, n, l) {
  return Ui(
    gt(
      e,
      t,
      s,
      n,
      l,
      !0
    )
  );
}
function tn(e) {
  return e ? e.__v_isVNode === !0 : !1;
}
function ns(e, t) {
  return e.type === t.type && e.key === t.key;
}
const Li = ({ key: e }) => e ?? null, Es = ({
  ref: e,
  ref_key: t,
  ref_for: s
}) => (typeof e == "number" && (e = "" + e), e != null ? me(e) || /* @__PURE__ */ De(e) || te(e) ? { i: Re, r: e, k: t, f: !!s } : e : null);
function i(e, t = null, s = null, n = 0, l = null, o = e === V ? 0 : 1, a = !1, r = !1) {
  const c = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e,
    props: t,
    key: t && Li(t),
    ref: t && Es(t),
    scopeId: pi,
    slotScopeIds: null,
    children: s,
    component: null,
    suspense: null,
    ssContent: null,
    ssFallback: null,
    dirs: null,
    transition: null,
    el: null,
    anchor: null,
    target: null,
    targetStart: null,
    targetAnchor: null,
    staticCount: 0,
    shapeFlag: o,
    patchFlag: n,
    dynamicProps: l,
    dynamicChildren: null,
    appContext: null,
    ctx: Re
  };
  return r ? (Us(c, s), o & 128 && e.normalize(c)) : s && (c.shapeFlag |= me(s) ? 8 : 16), vs > 0 && // avoid a block node from tracking itself
  !a && // has current parent block
  We && // presence of a patch flag indicates this node needs patching on updates.
  // component nodes also should always be patched, because even if the
  // component doesn't need to update, it needs to persist the instance on to
  // the next vnode so that it can be properly unmounted later.
  (c.patchFlag > 0 || o & 6) && // the EVENTS flag is only for hydration and if it is the only flag, the
  // vnode should not be considered dynamic due to handler caching.
  c.patchFlag !== 32 && We.push(c), c;
}
const gt = Fr;
function Fr(e, t = null, s = null, n = 0, l = null, o = !1) {
  if ((!e || e === bi) && (e = Xe), tn(e)) {
    const r = Zt(
      e,
      t,
      !0
      /* mergeRef: true */
    );
    return s && Us(r, s), vs > 0 && !o && We && (r.shapeFlag & 6 ? We[We.indexOf(e)] = r : We.push(r)), r.patchFlag = -2, r;
  }
  if (Yr(e) && (e = e.__vccOpts), t) {
    t = Ur(t);
    let { class: r, style: c } = t;
    r && !me(r) && (t.class = ge(r)), ce(c) && (/* @__PURE__ */ Vn(c) && !Q(c) && (c = Fe({}, c)), t.style = es(c));
  }
  const a = me(e) ? 1 : Fi(e) ? 128 : Xs(e) ? 64 : ce(e) ? 4 : te(e) ? 2 : 0;
  return i(
    e,
    t,
    s,
    n,
    l,
    a,
    o,
    !0
  );
}
function Ur(e) {
  return e ? /* @__PURE__ */ Vn(e) || Ei(e) ? Fe({}, e) : e : null;
}
function Zt(e, t, s = !1, n = !1) {
  const { props: l, ref: o, patchFlag: a, children: r, transition: c } = e, f = t ? Lr(l || {}, t) : l, h = {
    __v_isVNode: !0,
    __v_skip: !0,
    type: e.type,
    props: f,
    key: f && Li(f),
    ref: t && t.ref ? (
      // #2078 in the case of <component :is="vnode" ref="extra"/>
      // if the vnode itself already has a ref, cloneVNode will need to merge
      // the refs so the single vnode can be set on multiple refs
      s && o ? Q(o) ? o.concat(Es(t)) : [o, Es(t)] : Es(t)
    ) : o,
    scopeId: e.scopeId,
    slotScopeIds: e.slotScopeIds,
    children: r,
    target: e.target,
    targetStart: e.targetStart,
    targetAnchor: e.targetAnchor,
    staticCount: e.staticCount,
    shapeFlag: e.shapeFlag,
    // if the vnode is cloned with extra props, we can no longer assume its
    // existing patch flag to be reliable and need to add the FULL_PROPS flag.
    // note: preserve flag for fragments since they use the flag for children
    // fast paths only.
    patchFlag: t && e.type !== V ? a === -1 ? 16 : a | 16 : a,
    dynamicProps: e.dynamicProps,
    dynamicChildren: e.dynamicChildren,
    appContext: e.appContext,
    dirs: e.dirs,
    transition: c,
    // These should technically only be non-null on mounted VNodes. However,
    // they *should* be copied for kept-alive vnodes. So we just always copy
    // them since them being non-null during a mount doesn't affect the logic as
    // they will simply be overwritten.
    component: e.component,
    suspense: e.suspense,
    ssContent: e.ssContent && Zt(e.ssContent),
    ssFallback: e.ssFallback && Zt(e.ssFallback),
    placeholder: e.placeholder,
    el: e.el,
    anchor: e.anchor,
    ctx: e.ctx,
    ce: e.ce,
    cacheIndex: e.cacheIndex
  };
  return c && n && js(
    h,
    c.clone(h)
  ), h;
}
function nt(e = " ", t = 0) {
  return gt(en, null, e, t);
}
function W(e = "", t = !1) {
  return t ? (g(), pe(Xe, null, e)) : gt(Xe, null, e);
}
function ht(e) {
  return e == null || typeof e == "boolean" ? gt(Xe) : Q(e) ? gt(
    V,
    null,
    // #3666, avoid reference pollution when reusing vnode
    e.slice()
  ) : tn(e) ? xt(e) : gt(en, null, String(e));
}
function xt(e) {
  return e.el === null && e.patchFlag !== -1 || e.memo ? e : Zt(e);
}
function Us(e, t) {
  let s = 0;
  const { shapeFlag: n } = e;
  if (t == null)
    t = null;
  else if (Q(t))
    s = 16;
  else if (typeof t == "object")
    if (n & 65) {
      const l = t.default;
      l && (l._c && (l._d = !1), Us(e, l()), l._c && (l._d = !0));
      return;
    } else {
      s = 32;
      const l = t._;
      !l && !Ei(t) ? t._ctx = Re : l === 3 && Re && (Re.slots._ === 1 ? t._ = 1 : (t._ = 2, e.patchFlag |= 1024));
    }
  else if (te(t)) {
    if (n & 65) {
      Us(e, { default: t });
      return;
    }
    t = { default: t, _ctx: Re }, s = 32;
  } else
    t = String(t), n & 64 ? (s = 16, t = [nt(t)]) : s = 8;
  e.children = t, e.shapeFlag |= s;
}
function Lr(...e) {
  const t = {};
  for (let s = 0; s < e.length; s++) {
    const n = e[s];
    for (const l in n)
      if (l === "class")
        t.class !== n.class && (t.class = ge([t.class, n.class]));
      else if (l === "style")
        t.style = es([t.style, n.style]);
      else if (Ks(l)) {
        const o = t[l], a = n[l];
        a && o !== a && !(Q(o) && o.includes(a)) ? t[l] = o ? [].concat(o, a) : a : a == null && o == null && // mergeProps({ 'onUpdate:modelValue': undefined }) should not retain
        // the model listener.
        !Bs(l) && (t[l] = a);
      } else l !== "" && (t[l] = n[l]);
  }
  return t;
}
function dt(e, t, s, n = null) {
  it(e, t, 7, [
    s,
    n
  ]);
}
const Vr = xi();
let Vi = 0;
function Hr() {
  return Vi;
}
function Kr(e, t, s) {
  const n = e.type, l = (t ? t.appContext : e.appContext) || Vr, o = {
    uid: Vi++,
    vnode: e,
    type: n,
    parent: t,
    appContext: l,
    root: null,
    // to be immediately set
    next: null,
    subTree: null,
    // will be set synchronously right after creation
    effect: null,
    update: null,
    // will be set synchronously right after creation
    job: null,
    scope: new ho(
      !0
      /* detached */
    ),
    render: null,
    proxy: null,
    exposed: null,
    exposeProxy: null,
    withProxy: null,
    provides: t ? t.provides : Object.create(l.provides),
    ids: t ? t.ids : ["", 0, 0],
    accessCache: null,
    renderCache: [],
    // local resolved assets
    components: null,
    directives: null,
    // resolved props and emits options
    propsOptions: Ii(n, l),
    emitsOptions: Si(n, l),
    // emit
    emit: null,
    // to be set immediately
    emitted: null,
    // props default value
    propsDefaults: fe,
    // inheritAttrs
    inheritAttrs: n.inheritAttrs,
    // state
    ctx: fe,
    data: fe,
    props: fe,
    attrs: fe,
    slots: fe,
    refs: fe,
    setupState: fe,
    setupContext: null,
    // suspense related
    suspense: s,
    suspenseId: s ? s.pendingId : 0,
    asyncDep: null,
    asyncResolved: !1,
    // lifecycle hooks
    // not using enums here because it results in computed properties
    isMounted: !1,
    isUnmounted: !1,
    isDeactivated: !1,
    bc: null,
    c: null,
    bm: null,
    m: null,
    bu: null,
    u: null,
    um: null,
    bum: null,
    da: null,
    a: null,
    rtg: null,
    rtc: null,
    ec: null,
    sp: null
  };
  return o.ctx = { _: o }, o.root = t ? t.root : o, o.emit = kr.bind(null, o), e.ce && e.ce(o), o;
}
let je = null;
const Br = () => je || Re;
let Ls, ms;
{
  const e = zs(), t = (s, n) => {
    let l;
    return (l = e[s]) || (l = e[s] = []), l.push(n), (o) => {
      l.length > 1 ? l.forEach((a) => a(o)) : l[0](o);
    };
  };
  Ls = t(
    "__VUE_INSTANCE_SETTERS__",
    (s) => je = s
  ), ms = t(
    "__VUE_SSR_SETTERS__",
    (s) => gs = s
  );
}
const $s = (e) => {
  const t = je;
  return Ls(e), e.scope.on(), () => {
    e.scope.off(), Ls(t);
  };
}, kl = () => {
  je && je.scope.off(), Ls(null);
};
function Hi(e) {
  return e.vnode.shapeFlag & 4;
}
let gs = !1;
function qr(e, t = !1, s = !1) {
  t && ms(t);
  const { props: n, children: l } = e.vnode, o = Hi(e);
  Tr(e, n, o, t), Pr(e, l, s || t);
  const a = o ? Wr(e, t) : void 0;
  return t && ms(!1), a;
}
function Wr(e, t) {
  const s = e.type;
  e.accessCache = /* @__PURE__ */ Object.create(null), e.proxy = new Proxy(e.ctx, fr);
  const { setup: n } = s;
  if (n) {
    _t();
    const l = e.setupContext = n.length > 1 ? zr(e) : null, o = $s(e), a = ks(
      n,
      e,
      0,
      [
        e.props,
        l
      ]
    ), r = Ul(a);
    if (yt(), o(), (r || e.sp) && !Xt(e) && gi(e), r) {
      if (a.then(kl, kl), t)
        return a.then((c) => {
          ms(!0);
          try {
            $l(e, c, t);
          } finally {
            ms(!1);
          }
        }).catch((c) => {
          Ys(c, e, 0);
        });
      e.asyncDep = a;
    } else
      $l(e, a);
  } else
    Ki(e);
}
function $l(e, t, s) {
  te(t) ? e.type.__ssrInlineRender ? e.ssrRender = t : e.render = t : ce(t) && (e.setupState = ri(t)), Ki(e);
}
function Ki(e, t, s) {
  const n = e.type;
  e.render || (e.render = n.render || mt);
  {
    const l = $s(e);
    _t();
    try {
      pr(e);
    } finally {
      yt(), l();
    }
  }
}
const Jr = {
  get(e, t) {
    return Ne(e, "get", ""), e[t];
  }
};
function zr(e) {
  const t = (s) => {
    e.exposed = s || {};
  };
  return {
    attrs: new Proxy(e.attrs, Jr),
    slots: e.slots,
    emit: e.emit,
    expose: t
  };
}
function sn(e) {
  return e.exposed ? e.exposeProxy || (e.exposeProxy = new Proxy(ri(Ro(e.exposed)), {
    get(t, s) {
      if (s in t)
        return t[s];
      if (s in ds)
        return ds[s](e);
    },
    has(t, s) {
      return s in t || s in ds;
    }
  })) : e.proxy;
}
function Gr(e, t = !0) {
  return te(e) ? e.displayName || e.name : e.name || t && e.__name;
}
function Yr(e) {
  return te(e) && "__vccOpts" in e;
}
const Ce = (e, t) => /* @__PURE__ */ Fo(e, t, gs), Xr = "3.5.44";
/**
* @vue/runtime-dom v3.5.44
* (c) 2018-present Yuxi (Evan) You and Vue contributors
* @license MIT
**/
let On;
const wl = typeof window < "u" && window.trustedTypes;
if (wl)
  try {
    On = /* @__PURE__ */ wl.createPolicy("vue", {
      createHTML: (e) => e
    });
  } catch {
  }
const Bi = On ? (e) => On.createHTML(e) : (e) => e, Qr = "http://www.w3.org/2000/svg", Zr = "http://www.w3.org/1998/Math/MathML", $t = typeof document < "u" ? document : null, xl = $t && /* @__PURE__ */ $t.createElement("template"), ea = {
  insert: (e, t, s) => {
    t.insertBefore(e, s || null);
  },
  remove: (e) => {
    const t = e.parentNode;
    t && t.removeChild(e);
  },
  createElement: (e, t, s, n) => {
    const l = t === "svg" ? $t.createElementNS(Qr, e) : t === "mathml" ? $t.createElementNS(Zr, e) : s ? $t.createElement(e, { is: s }) : $t.createElement(e);
    return e === "select" && n && n.multiple != null && l.setAttribute("multiple", n.multiple), l;
  },
  createText: (e) => $t.createTextNode(e),
  createComment: (e) => $t.createComment(e),
  setText: (e, t) => {
    e.nodeValue = t;
  },
  setElementText: (e, t) => {
    e.textContent = t;
  },
  parentNode: (e) => e.parentNode,
  nextSibling: (e) => e.nextSibling,
  querySelector: (e) => $t.querySelector(e),
  setScopeId(e, t) {
    e.setAttribute(t, "");
  },
  // __UNSAFE__
  // Reason: innerHTML.
  // Static content here can only come from compiled templates.
  // As long as the user only uses trusted templates, this is safe.
  insertStaticContent(e, t, s, n, l, o) {
    const a = s ? s.previousSibling : t.lastChild;
    if (l && (l === o || l.nextSibling))
      for (; t.insertBefore(l.cloneNode(!0), s), !(l === o || !(l = l.nextSibling)); )
        ;
    else {
      xl.innerHTML = Bi(
        n === "svg" ? `<svg>${e}</svg>` : n === "mathml" ? `<math>${e}</math>` : e
      );
      const r = xl.content;
      if (n === "svg" || n === "mathml") {
        const c = r.firstChild;
        for (; c.firstChild; )
          r.appendChild(c.firstChild);
        r.removeChild(c);
      }
      t.insertBefore(r, s);
    }
    return [
      // first
      a ? a.nextSibling : t.firstChild,
      // last
      s ? s.previousSibling : t.lastChild
    ];
  }
}, ta = /* @__PURE__ */ Symbol("_vtc");
function sa(e, t, s) {
  const n = e[ta];
  n && (t = (t ? [t, ...n] : [...n]).join(" ")), t == null ? e.removeAttribute("class") : s ? e.setAttribute("class", t) : e.className = t;
}
const Sl = /* @__PURE__ */ Symbol("_vod"), na = /* @__PURE__ */ Symbol("_vsh"), la = /* @__PURE__ */ Symbol(""), ia = /(?:^|;)\s*display\s*:/;
function oa(e, t, s) {
  const n = e.style, l = me(s);
  let o = !1;
  if (s && !l) {
    if (t)
      if (me(t))
        for (const a of t.split(";")) {
          const r = a.slice(0, a.indexOf(":")).trim();
          s[r] == null && os(n, r, "");
        }
      else
        for (const a in t)
          s[a] == null && os(n, a, "");
    for (const a in s) {
      a === "display" && (o = !0);
      const r = s[a];
      r != null ? aa(
        e,
        a,
        !me(t) && t ? t[a] : void 0,
        r
      ) || os(n, a, r) : os(n, a, "");
    }
  } else if (l) {
    if (t !== s) {
      const a = n[la];
      a && (s += ";" + a), n.cssText = s, o = ia.test(s);
    }
  } else t && e.removeAttribute("style");
  Sl in e && ((!l || t !== s) && (e[Sl] = o ? n.display : ""), e[na] && (n.display = "none"));
}
const Cs = /\s*!important$/;
function os(e, t, s) {
  if (Q(s))
    s.forEach((n) => os(e, t, n));
  else if (s == null && (s = ""), t.startsWith("--"))
    Cs.test(s) ? e.setProperty(t, s.replace(Cs, ""), "important") : e.setProperty(t, s);
  else {
    const n = ra(e, t);
    Cs.test(s) ? e.setProperty(
      Ft(n),
      s.replace(Cs, ""),
      "important"
    ) : e[n] = s;
  }
}
const Cl = ["Webkit", "Moz", "ms"], vn = {};
function ra(e, t) {
  const s = vn[t];
  if (s)
    return s;
  let n = Ve(t);
  if (n !== "filter" && n in e)
    return vn[t] = n;
  n = Ws(n);
  for (let l = 0; l < Cl.length; l++) {
    const o = Cl[l] + n;
    if (o in e)
      return vn[t] = o;
  }
  return t;
}
function aa(e, t, s, n) {
  return e.tagName === "TEXTAREA" && (t === "width" || t === "height") && me(n) && s === n;
}
const Tl = "http://www.w3.org/1999/xlink";
function Al(e, t, s, n, l, o = uo(t)) {
  n && t.startsWith("xlink:") ? s == null ? e.removeAttributeNS(Tl, t.slice(6, t.length)) : e.setAttributeNS(Tl, t, s) : s == null || o && !Kl(s) ? e.removeAttribute(t) : e.setAttribute(
    t,
    o ? "" : lt(s) ? String(s) : s
  );
}
function Ol(e, t, s, n, l) {
  if (t === "innerHTML" || t === "textContent") {
    s != null && (e[t] = t === "innerHTML" ? Bi(s) : s);
    return;
  }
  const o = e.tagName;
  if (t === "value" && o !== "PROGRESS" && // custom elements may use _value internally
  !o.includes("-")) {
    const r = o === "OPTION" ? e.getAttribute("value") || "" : e.value, c = s == null ? (
      // #11647: value should be set as empty string for null and undefined,
      // but <input type="checkbox"> should be set as 'on'.
      e.type === "checkbox" ? "on" : ""
    ) : String(s);
    (r !== c || !("_value" in e)) && (e.value = c), s == null && e.removeAttribute(t), e._value = s;
    return;
  }
  let a = !1;
  if (s === "" || s == null) {
    const r = typeof e[t];
    r === "boolean" ? s = Kl(s) : s == null && r === "string" ? (s = "", a = !0) : r === "number" && (s = 0, a = !0);
  }
  try {
    e[t] = s;
  } catch {
  }
  a && e.removeAttribute(l || t);
}
function Ht(e, t, s, n) {
  e.addEventListener(t, s, n);
}
function ua(e, t, s, n) {
  e.removeEventListener(t, s, n);
}
const El = /* @__PURE__ */ Symbol("_vei");
function ca(e, t, s, n, l = null) {
  const o = e[El] || (e[El] = {}), a = o[t];
  if (n && a)
    a.value = n;
  else {
    const [r, c] = pa(t);
    if (n) {
      const f = o[t] = ma(
        n,
        l
      );
      Ht(e, r, f, c);
    } else a && (ua(e, r, a, c), o[t] = void 0);
  }
}
const da = /(Once|Passive|Capture)$/, fa = /^on:?(?:Once|Passive|Capture)$/;
function pa(e) {
  let t, s;
  for (; (s = e.match(da)) && !fa.test(e); )
    t || (t = {}), e = e.slice(0, e.length - s[1].length), t[s[1].toLowerCase()] = !0;
  return [e[2] === ":" ? e.slice(3) : Ft(e.slice(2)), t];
}
let mn = 0;
const ha = /* @__PURE__ */ Promise.resolve(), va = () => mn || (ha.then(() => mn = 0), mn = Date.now());
function ma(e, t) {
  const s = (n) => {
    if (!n._vts)
      n._vts = Date.now();
    else if (n._vts <= s.attached)
      return;
    const l = s.value;
    if (Q(l)) {
      const o = n.stopImmediatePropagation;
      n.stopImmediatePropagation = () => {
        o.call(n), n._stopped = !0;
      };
      const a = l.slice(), r = [n];
      for (let c = 0; c < a.length && !n._stopped; c++) {
        const f = a[c];
        f && it(
          f,
          t,
          5,
          r
        );
      }
    } else
      it(
        l,
        t,
        5,
        [n]
      );
  };
  return s.value = e, s.attached = va(), s;
}
const Pl = (e) => e.charCodeAt(0) === 111 && e.charCodeAt(1) === 110 && // lowercase letter
e.charCodeAt(2) > 96 && e.charCodeAt(2) < 123, ga = (e, t, s, n, l, o) => {
  const a = l === "svg";
  t === "class" ? sa(e, n, a) : t === "style" ? oa(e, s, n) : Ks(t) ? Bs(t) || ca(e, t, s, n, o) : (t[0] === "." ? (t = t.slice(1), !0) : t[0] === "^" ? (t = t.slice(1), !1) : _a(e, t, n, a)) ? (Ol(e, t, n), !e.tagName.includes("-") && (t === "value" || t === "checked" || t === "selected") && Al(e, t, n, a, o, t !== "value")) : /* #11081 force set props for possible async custom element */ e._isVueCE && // #12408 check if it's declared prop or it's async custom element
  (ya(e, t) || // @ts-expect-error _def is private
  e._def.__asyncLoader && (/[A-Z]/.test(t) || !me(n))) ? Ol(e, Ve(t), n, o, t) : (t === "true-value" ? e._trueValue = n : t === "false-value" && (e._falseValue = n), Al(e, t, n, a));
};
function _a(e, t, s, n) {
  if (n)
    return !!(t === "innerHTML" || t === "textContent" || t in e && Pl(t) && te(s));
  if (t === "spellcheck" || t === "draggable" || t === "translate" || t === "autocorrect" || t === "sandbox" && e.tagName === "IFRAME" || t === "form" || t === "list" && e.tagName === "INPUT" || t === "type" && e.tagName === "TEXTAREA")
    return !1;
  if (t === "width" || t === "height") {
    const l = e.tagName;
    if (l === "IMG" || l === "VIDEO" || l === "CANVAS" || l === "SOURCE")
      return !1;
  }
  return Pl(t) && me(s) ? !1 : t in e;
}
function ya(e, t) {
  const s = (
    // @ts-expect-error _def is private
    e._def.props
  );
  if (!s)
    return !1;
  const n = Ve(t);
  return Array.isArray(s) ? s.some((l) => Ve(l) === n) : Object.keys(s).some((l) => Ve(l) === n);
}
const Vs = (e) => {
  const t = e.props["onUpdate:modelValue"] || !1;
  return Q(t) ? (s) => As(t, s) : t;
};
function ba(e) {
  e.target.composing = !0;
}
function Il(e) {
  const t = e.target;
  t.composing && (t.composing = !1, t.dispatchEvent(new Event("input")));
}
const Bt = /* @__PURE__ */ Symbol("_assign"), Ts = /* @__PURE__ */ Symbol("_initialValue");
function gn(e, t, s) {
  return t && (e = e.trim()), s && (e = Js(e)), e;
}
const ze = {
  created(e, { modifiers: { lazy: t, trim: s, number: n } }, l) {
    e.parentNode && (e.type === "text" ? e[Ts] = e.defaultValue.replace(/[\r\n]/g, "") : e.type === "textarea" && (e[Ts] = e.defaultValue.replace(/\r\n?/g, `
`))), e[Bt] = Vs(l);
    const o = n || l.props && l.props.type === "number";
    Ht(e, t ? "change" : "input", (a) => {
      a.target.composing || e[Bt](gn(e.value, s, o));
    }), (s || o) && Ht(e, "change", () => {
      e.value = gn(e.value, s, o);
    }), t || (Ht(e, "compositionstart", ba), Ht(e, "compositionend", Il), Ht(e, "change", Il));
  },
  // set value on mounted so it's after min/max for type="range"
  mounted(e, { value: t, modifiers: { trim: s, number: n } }) {
    const l = t ?? "", o = e[Ts];
    delete e[Ts], o !== void 0 && (e.type === "text" || e.type === "textarea") && e.value !== o ? e[Bt](gn(e.value, s, n)) : e.value = l;
  },
  beforeUpdate(e, { value: t, oldValue: s, modifiers: { lazy: n, trim: l, number: o } }, a) {
    if (e[Bt] = Vs(a), e.composing) return;
    const r = (o || e.type === "number") && !/^0\d/.test(e.value) ? Js(e.value) : e.value, c = t ?? "";
    if (r === c)
      return;
    const f = e.getRootNode();
    (f instanceof Document || f instanceof ShadowRoot) && f.activeElement === e && e.type !== "range" && (n && t === s || l && e.value.trim() === c) || (e.value = c);
  }
}, wt = {
  // <select multiple> value need to be deep traversed
  deep: !0,
  created(e, { value: t, modifiers: { number: s } }, n) {
    e._modelValue = t, Ht(e, "change", () => {
      const l = Array.prototype.filter.call(e.options, (c) => c.selected).map(
        (c) => s ? Js(Hs(c)) : Hs(c)
      ), o = e.multiple, a = o ? Jt(e._modelValue) ? new Set(l) : l : l[0], r = e._pendingValue = [
        o,
        o ? Q(a) ? l.slice() : l : a
      ];
      try {
        e[Bt](a);
      } finally {
        Ns(() => {
          e._pendingValue === r && (e._pendingValue = void 0);
        });
      }
    }), e[Bt] = Vs(n);
  },
  // set value in mounted & updated because <select> relies on its children
  // <option>s.
  mounted(e, { value: t }) {
    Rl(e, t);
  },
  beforeUpdate(e, { value: t }, s) {
    e._modelValue = t, e[Bt] = Vs(s);
  },
  updated(e, { value: t }) {
    const s = e._pendingValue;
    e._pendingValue = void 0, (!s || s[0] !== e.multiple || !ka(t, s[1], s[0])) && Rl(e, t);
  }
};
function ka(e, t, s) {
  if (!s || Q(e)) return jt(e, t);
  if (Jt(e)) {
    if (e.size !== t.length) return !1;
    for (const n of t)
      if (!e.has(n)) return !1;
    return !0;
  }
  return !1;
}
function Rl(e, t) {
  const s = e.multiple, n = Q(t);
  if (!(s && !n && !Jt(t))) {
    for (let l = 0, o = e.options.length; l < o; l++) {
      const a = e.options[l], r = Hs(a);
      if (s)
        if (n) {
          const c = typeof r;
          c === "string" || c === "number" ? a.selected = t.some((f) => String(f) === String(r)) : a.selected = po(t, r) > -1;
        } else
          a.selected = t.has(r);
      else if (jt(Hs(a), t)) {
        e.selectedIndex !== l && (e.selectedIndex = l);
        return;
      }
    }
    !s && e.selectedIndex !== -1 && (e.selectedIndex = -1);
  }
}
function Hs(e) {
  return "_value" in e ? e._value : e.value;
}
const $a = ["ctrl", "shift", "alt", "meta"], wa = {
  stop: (e) => e.stopPropagation(),
  prevent: (e) => e.preventDefault(),
  self: (e) => e.target !== e.currentTarget,
  ctrl: (e) => !e.ctrlKey,
  shift: (e) => !e.shiftKey,
  alt: (e) => !e.altKey,
  meta: (e) => !e.metaKey,
  left: (e) => "button" in e && e.button !== 0,
  middle: (e) => "button" in e && e.button !== 1,
  right: (e) => "button" in e && e.button !== 2,
  exact: (e, t) => $a.some((s) => e[`${s}Key`] && !t.includes(s))
}, qi = (e, t) => {
  if (!e) return e;
  const s = e._withMods || (e._withMods = {}), n = t.join(".");
  return s[n] || (s[n] = ((l, ...o) => {
    for (let a = 0; a < t.length; a++) {
      const r = wa[t[a]];
      if (r && r(l, t)) return;
    }
    return e(l, ...o);
  }));
}, xa = {
  esc: "escape",
  space: " ",
  up: "arrow-up",
  left: "arrow-left",
  right: "arrow-right",
  down: "arrow-down",
  delete: "backspace"
}, Sa = (e, t) => {
  const s = e._withKeys || (e._withKeys = {}), n = t.join(".");
  return s[n] || (s[n] = ((l) => {
    if (!("key" in l))
      return;
    const o = Ft(l.key);
    if (t.some(
      (a) => a === o || xa[a] === o
    ))
      return e(l);
  }));
}, Ca = /* @__PURE__ */ Fe({ patchProp: ga }, ea);
let Nl;
function Ta() {
  return Nl || (Nl = Rr(Ca));
}
const Aa = ((...e) => {
  const t = Ta().createApp(...e), { mount: s } = t;
  return t.mount = (n) => {
    const l = Ea(n);
    if (!l) return;
    const o = t._component;
    !te(o) && !o.render && !o.template && (o.template = l.innerHTML), l.nodeType === 1 && (l.textContent = "");
    const a = s(l, !1, Oa(l));
    return l instanceof Element && (l.removeAttribute("v-cloak"), l.setAttribute("data-v-app", "")), a;
  }, t;
});
function Oa(e) {
  if (e instanceof SVGElement)
    return "svg";
  if (typeof MathMLElement == "function" && e instanceof MathMLElement)
    return "mathml";
}
function Ea(e) {
  return me(e) ? document.querySelector(e) : e;
}
const zn = "kms-token";
function Wi() {
  return localStorage.getItem(zn);
}
function Pa(e) {
  localStorage.setItem(zn, e);
}
function nn() {
  localStorage.removeItem(zn);
}
function _s(e = {}) {
  const t = Wi();
  return t ? { Authorization: `Bearer ${t}`, ...e } : { ...e };
}
function Gn(e) {
  const t = new URL(e, location.origin);
  if (t.origin !== location.origin)
    throw new Error("仅允许同源请求，禁止转发令牌到外部站点");
  return t;
}
function Yn(e, t, s = "") {
  const n = (e == null ? void 0 : e.detail) || (e == null ? void 0 : e.message) || `请求失败 (${t})`, l = (e == null ? void 0 : e.request_id) || s;
  return l ? `${n}（请求ID ${l}）` : n;
}
async function Rt(e, t = {}) {
  const { onUnauthorized: s, headers: n = {}, ...l } = t;
  Gn(e);
  const o = await fetch(e, {
    ...l,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ..._s(n) }
  }), a = await o.json().catch(() => ({}));
  if (!o.ok)
    throw o.status === 401 && (typeof s == "function" ? await s(o, a) : nn()), new Error(Yn(a, o.status, o.headers.get("X-Request-ID")));
  return a;
}
async function En(e, t, s = {}) {
  Gn(e);
  const n = await fetch(e, { method: "POST", body: t, headers: _s(s.headers || {}) }), l = await n.json().catch(() => ({}));
  if (!n.ok) throw new Error(Yn(l, n.status, n.headers.get("X-Request-ID")));
  return l;
}
async function Ji(e, t, s, n = {}) {
  Gn(e);
  const l = await fetch(e, {
    method: "POST",
    cache: "no-store",
    headers: _s({ "Content-Type": "application/json", ...n.headers || {} }),
    body: JSON.stringify(t)
  });
  if (!l.ok) {
    const c = await l.json().catch(() => ({}));
    throw new Error(Yn(c, l.status, l.headers.get("X-Request-ID")));
  }
  const o = l.body.getReader(), a = new TextDecoder();
  let r = "";
  for (; ; ) {
    const { value: c, done: f } = await o.read();
    if (f) break;
    r += a.decode(c, { stream: !0 });
    const h = r.split(`

`);
    r = h.pop() ?? "";
    for (const k of h) {
      const R = k.split(`
`).find((O) => O.startsWith("data:"));
      if (R)
        try {
          s(JSON.parse(R.slice(5).trim()));
        } catch {
        }
    }
  }
}
var be, Ae;
class zi {
  /**
   * @param {object} opts
   * @param {string} [opts.base]    KMS 业务 API 前缀，默认 /kms/api
   * @param {string} [opts.gateway] 网关前缀，默认 /gw/api/v1
   * @param {(info:object)=>void} [opts.onUnauthorized] 401 回调（工作台用于回退登录态）
   */
  constructor(t = {}) {
    tl(this, be);
    this.base = t.base || "/kms/api", this.gateway = t.gateway || "/gw/api/v1", this.onUnauthorized = t.onUnauthorized;
  }
  /* ================= 认证 ================= */
  async login(t, s) {
    const n = await Te(this, be, Ae).call(this, "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee_no: t, password: s })
    }), l = n.token || n.access_token;
    return l && Pa(l), n;
  }
  logout() {
    nn();
  }
  me() {
    return Te(this, be, Ae).call(this, "/auth/me");
  }
  changePassword(t, s) {
    return Te(this, be, Ae).call(this, "/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password: t, new_password: s })
    });
  }
  /* ================= 问答（单轮，企业路径） ================= */
  ask(t) {
    return Te(this, be, Ae).call(this, "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: t })
    });
  }
  /** 流式问答；onEvent 收到单条 JSON 帧。后端复用 /chat 端点，以 ?stream=true 触发 SSE */
  askStream(t, s) {
    return Ji(`${this.base}/chat?stream=true`, { question: t }, s, {});
  }
  feedback(t, s, n = "") {
    return Te(this, be, Ae).call(this, "/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: t, rating: s, comment: n })
    });
  }
  /* ================= 知识检索与目录 ================= */
  /** 授权过滤后的资料片段（对应 MCP search_knowledge） */
  search(t, s = 5, n) {
    return Te(this, be, Ae).call(this, "/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: t, top_k: s, max_classification: n })
    });
  }
  /** 文档列表。sort="asc"（默认）按文档编号从小到大，与列表展示口径一致；
   *  「最近入库」类视图必须显式传 "desc"，否则会拿到最旧的一批。
   *
   *  keyword 走服务端全库过滤（后端 q 参数）：列表正序分页，新审批通过的
   *  文档总在末页，只在当前页里筛会搜不到刚通过的文档。 */
  listDocuments(t = 0, s = 20, n = "asc", l = "") {
    const o = String(l || "").trim(), a = o ? `&q=${encodeURIComponent(o)}` : "";
    return Te(this, be, Ae).call(this, `/documents?offset=${t}&limit=${s}&sort=${encodeURIComponent(n)}${a}`);
  }
  document(t) {
    return Te(this, be, Ae).call(this, `/documents/${t}`);
  }
  inspect(t) {
    return Te(this, be, Ae).call(this, `/documents/${t}/inspect`);
  }
  recommendations(t = 10, s = {}) {
    const n = new URLSearchParams({ top_n: String(t) });
    return s.seed_doc_id && n.set("seed_doc_id", String(s.seed_doc_id)), s.seed_text && n.set("seed_text", s.seed_text), Te(this, be, Ae).call(this, `/recommendations?${n}`);
  }
  /* ================= 文档维护（双人审批，不旁路） ================= */
  /** 上传后进入草稿；发布必须走 propose → decide */
  upload(t, s) {
    const n = new FormData();
    return n.append("file", t), s != null && n.append("classification", String(s)), En(`${this.base}/documents`, n);
  }
  managedDocuments(t = 100) {
    return Te(this, be, Ae).call(this, `/managed-documents?limit=${t}`);
  }
  /** 提交发布/变更申请（生成工单；批准由审批员在 Web 端完成） */
  propose(t, s) {
    return Te(this, be, Ae).call(this, `/policy-requests/${t}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s)
    });
  }
  requests() {
    return Te(this, be, Ae).call(this, "/governance/requests");
  }
  decide(t, s) {
    return Te(this, be, Ae).call(this, `/governance/requests/${t}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approve: s })
    });
  }
  /* ================= 组织与审计 ================= */
  users() {
    return Te(this, be, Ae).call(this, "/admin/users");
  }
  departments() {
    return Te(this, be, Ae).call(this, "/admin/departments");
  }
  /** 安全职级列表（只读，固定 L0~L3，由 HR 维护）。
   *  前端需要它把 classification 数字译成名称——不写死在前端，
   *  免得职级调整后名称对不上。 */
  levels() {
    return Te(this, be, Ae).call(this, "/admin/levels");
  }
  auditEvents(t = {}) {
    const s = new URLSearchParams(t).toString();
    return Te(this, be, Ae).call(this, `/admin/audit-events${s ? `?${s}` : ""}`);
  }
  /* ================= 网关侧（应用 / 嵌入） ================= */
  embedConfig() {
    return Rt(`${this.gateway}/embed/config`);
  }
  embedDocuments(t = 0, s = 20) {
    return Rt(`${this.gateway}/embed/documents?offset=${t}&limit=${s}`);
  }
  /* ================= MCP（与 REST 同源同权，供控制台复用） ================= */
  /** 调用 MCP 工具；企业路径需带员工令牌 */
  mcpCall(t, s = {}, n = 1) {
    return Rt(`${this.gateway}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18" },
      body: JSON.stringify({ jsonrpc: "2.0", id: n, method: "tools/call", params: { name: t, arguments: s } })
    });
  }
  mcpTools() {
    return Rt(`${this.gateway}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" })
    });
  }
  mcpMetrics() {
    return Rt(`${this.gateway}/mcp/metrics`);
  }
  /* ================= 应用治理自助（对应 MCP get_app_usage） ================= */
  /** 调用方应用近期用量（MCP 工具同源实现） */
  appUsage(t = 7) {
    return this.mcpCall("get_app_usage", { days: t });
  }
}
be = new WeakSet(), Ae = function(t, s = {}) {
  return Rt(this.base + t, { onUnauthorized: this.onUnauthorized, ...s });
};
new zi();
class Ia extends zi {
  /** 带查询串的 GET；空值参数不拼进 URL，避免出现 ?limit=undefined */
  _get(t, s = {}) {
    const n = new URLSearchParams(
      Object.entries(s).filter(([, l]) => l != null && l !== "")
    ).toString();
    return Rt(this.base + t + (n ? `?${n}` : ""), {
      onUnauthorized: this.onUnauthorized
    });
  }
  _post(t, s = {}, n = "POST") {
    return Rt(this.base + t, {
      method: n,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s),
      onUnauthorized: this.onUnauthorized
    });
  }
  /* ================= 系统 ================= */
  stats() {
    return this._get("/stats");
  }
  health() {
    return this._get("/health");
  }
  /* ================= 文档 ================= */
  /** 审批人候选：按「目标密级 + 目标归属部门数组」派生，已排除申请人本人。
   *  后端 routes_kms.py:319；前端拿到后供申请人自选，不自由填写。 */
  approverCandidates(t, s = []) {
    return this._get("/documents/approver-candidates", {
      classification: t,
      departments: JSON.stringify(s)
    });
  }
  /** 批量上传：返回批次 id，进度另行轮询 uploadBatch()。
   *  字段名必须与后端 routes_upload.py:319 的 Form 形参一致：
   *  level / departments(JSON 数组) / approver_id——写成 classification 会被后端
   *  当成未传，密级回落本人职级、部门回落本人部门、审批人随机指派，
   *  上传区三个联动下拉框全部失效（老版 app.js:1008 即此口径）。 */
  batchUpload(t, s, n = [], l = null) {
    const o = new FormData();
    for (const a of t) o.append("files", a, a.name);
    return s != null && o.append("level", String(s)), n && n.length && o.append("departments", JSON.stringify(n)), l != null && o.append("approver_id", String(l)), En(`${this.base}/documents/batch-upload`, o);
  }
  uploadBatch(t) {
    return this._get(`/upload/batches/${t}`);
  }
  /** 为已有文档上传新版本（显式更新入口）：走单文件接口 POST /documents。
   *  字段名与后端 routes_kms.upload_document 的 Form 形参一致——注意单文件
   *  接口密级字段是 classification（批量接口是 level，勿混）。
   *  target_document_id 指定目标 doc_id，文件名无需与原文件相同。 */
  uploadVersion(t, s, n, l = [], o = null, a = "") {
    const r = new FormData();
    return r.append("file", s, s.name), n != null && r.append("classification", String(n)), l && l.length && r.append("departments", JSON.stringify(l)), o != null && r.append("approver_id", String(o)), r.append("target_document_id", String(t)), a && a.trim() && r.append("update_reason", a.trim()), En(`${this.base}/documents`, r);
  }
  versions(t) {
    return this._get(`/documents/${t}/versions`);
  }
  /** 申请回滚（走审批，不直接生效）。approverId 留空则后端随机指派；
   *  指定时后端仍会在合格候选池里比对，池外一律 422。
   *
   *  classification / departments 是**申请人声明的目标态**（与「申请更新」
   *  同口径），不再由后端默默沿用文档当前值——工单上的「目标密级」必须是
   *  申请人写下、审批人据以复核的值，而不是系统从文档行里抄的。传 null
   *  才表示沿用当前值（兼容旧调用方）。 */
  rollback(t, s, n = null, l = "", o = null, a = null) {
    const r = {};
    return n != null && (r.approver_id = n), l && l.trim() && (r.reason = l.trim()), o != null && (r.classification = Number(o)), Array.isArray(a) && (r.departments = a), this._post(`/documents/${t}/versions/${s}/rollback`, r);
  }
  /** 下载原文：端点要 Bearer 鉴权，故走 fetch 取 blob，不能用裸 <a href> */
  async download(t, s = "") {
    const n = await fetch(`${this.base}/documents/${t}/download`, {
      headers: _s()
    });
    if (!n.ok) throw new Error(`下载失败 (${n.status})`);
    const l = await n.blob(), o = URL.createObjectURL(l), a = document.createElement("a");
    a.href = o, a.download = s || `document-${t}`, document.body.appendChild(a), a.click(), a.remove(), URL.revokeObjectURL(o);
  }
  /* ================= 个人统计 ================= */
  /** 个人中心的问答/文档统计（原知识中心栏目已下线，仅保留个人页在用的这一个） */
  knowledgePersonalStats() {
    return this._get("/knowledge/personal/stats");
  }
  /* ================= 会话 ================= */
  /** 带会话续接的流式问答。
   *  为什么不直接用 SDK 的 askStream()：它只发 {question}，不带 session_id，
   *  后端于是每轮都新开一个会话（uuid4），多轮上下文根本接不上。
   *  这里显式带上 session_id，让同一会话里的追问能命中历史。 */
  askStreamIn(t, s, n) {
    const l = { question: t };
    return s && (l.session_id = s), Ji(`${this.base}/chat?stream=true`, l, n, {});
  }
  conversations(t = 50) {
    return this._get("/conversations", { limit: t });
  }
  conversationHistory(t, s = 100) {
    return this._get(`/conversations/${encodeURIComponent(t)}/history`, { limit: s });
  }
  /* ================= 审计（运营审计只读） ================= */
  auditActions() {
    return this._get("/audit/audit-actions");
  }
  auditLogs(t = {}) {
    return this._get("/audit/audit-logs", t);
  }
  ingestStatus() {
    return this._get("/audit/ingest-status");
  }
  hrSyncHistory(t = 20) {
    return this._get("/audit/hr-sync/history", { limit: t });
  }
  /* ================= 工单 ================= */
  ticketModules() {
    return this._get("/tickets/modules");
  }
  ticketOptions() {
    return this._get("/tickets/options");
  }
  ticketsMine() {
    return this._get("/tickets/mine");
  }
  ticketsPendingApproval() {
    return this._get("/tickets/pending-approval");
  }
  ticketsDone() {
    return this._get("/tickets/done");
  }
  ticketsRecycleBin() {
    return this._get("/tickets/recycle-bin");
  }
  ticket(t) {
    return this._get(`/tickets/${t}`);
  }
  /** 待审附件下载：GET /tickets/{id}/files/{index} 返回文件流。
   *  端点要 Bearer 鉴权，走 fetch 取 blob；文件名优先取
   *  content-disposition（后端 RFC5987 编码），兜底 ticket_{id}_file_{n}。 */
  async ticketFile(t, s) {
    const n = await fetch(`${this.base}/tickets/${t}/files/${s}`, {
      headers: _s()
    });
    if (!n.ok) {
      const h = await n.json().catch(() => ({}));
      throw new Error(typeof h.detail == "string" ? h.detail : `下载失败 (${n.status})`);
    }
    const l = await n.blob(), o = n.headers.get("content-disposition") || "";
    let a = `ticket_${t}_file_${s}`;
    const r = o.match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i);
    if (r)
      try {
        a = decodeURIComponent(r[1]);
      } catch {
        a = r[1];
      }
    const c = URL.createObjectURL(l), f = document.createElement("a");
    f.href = c, f.download = a, document.body.appendChild(f), f.click(), f.remove(), URL.revokeObjectURL(c);
  }
  /** 发布审批（governance 体系）：所有层级上传/改属性自动触发的审批进度。
   *  返回我发起的 + 被指派给我审批的；后端 routes_kms.py:776。
   *  status 可选过滤（如 "pending" / "approved,rejected"）：
   *  「发布审批」tab 只看进行中，已决策历史归入「已完成」，避免重复展示。 */
  governanceRequests(t) {
    return this._get("/governance/requests" + (t ? `?status=${encodeURIComponent(t)}` : ""));
  }
  /** 发布审批决策：approve=true/false；仅被指派的审批人可调。 */
  decideRequest(t, s) {
    return this._post(
      `/governance/requests/${encodeURIComponent(t)}/decision`,
      { approve: s }
    );
  }
  /** module 必填；approver_id 留空则由后端按「同部门 + 职级够」指派 */
  createTicket(t, s = {}, n = null) {
    const l = { module: t, payload: s };
    return n != null && (l.approver_id = n), this._post("/tickets", l);
  }
  approveTicket(t, s = "") {
    return this._post(`/tickets/${t}/approve`, { comment: s });
  }
  rejectTicket(t, s = "", n = "") {
    return this._post(`/tickets/${t}/reject`, { comment: n, reason: s });
  }
  cancelTicket(t) {
    return this._post(`/tickets/${t}/cancel`, {});
  }
  /* 注：execute/refuse/executor-candidates 为两段式前的旧执行人接口，
   *  审批通过即系统自动执行，无执行人角色，前端不提供入口。 */
  /* ================= 通知 ================= */
  notifications() {
    return this._get("/notifications");
  }
  unreadCount() {
    return this._get("/notifications/unread-count");
  }
  markRead(t) {
    return this._post(`/notifications/${t}/read`, {}, "POST");
  }
  markAllRead() {
    return this._post("/notifications/read-all", {});
  }
  /* ================= 认证 ================= */
  /** 服务端登出（清理会话）；本地令牌无论如何都清掉 */
  async logoutApi() {
    try {
      await this._post("/auth/logout", {});
    } catch {
    }
    nn();
  }
}
const G = new Ia();
function qt(e) {
  if (!e) return 0;
  const t = e.security_level != null ? e.security_level : e.level, s = Number(t);
  return Number.isFinite(s) ? s : 0;
}
function Gi(e) {
  const t = Array.isArray(e) ? e : [];
  return t.length ? Math.max(...t.map((s) => Number(s.level) || 0)) : 0;
}
function Ra(e, t) {
  const n = (Array.isArray(t) ? t : []).find((l) => Number(l.level) === Number(e));
  return n ? n.name : `L${e}`;
}
function Na(e) {
  return `L${Number(e) || 0}`;
}
function Yi(e) {
  return !!e && qt(e) >= 2;
}
function Xi(e) {
  return !!e && !!e.is_active;
}
function Ma(e, t, s, n, l = !1) {
  if (!t || !t.is_active) return !1;
  if (l) {
    if (e == null) return qt(t) === 3;
    const c = Number(e);
    return c >= 0 && c <= qt(t);
  }
  let o = s;
  if (typeof o == "string")
    try {
      o = JSON.parse(o);
    } catch {
      o = o ? [o] : [];
    }
  Array.isArray(o) || (o = o ? [o] : []);
  const a = n || "";
  if (!o.length || !o.includes("*") && !o.includes(a)) return !1;
  if (e == null) return qt(t) === 3;
  const r = Number(e);
  return r >= 0 && r <= qt(t);
}
function ja(e, t) {
  if (!e) return null;
  const s = qt(e), n = Gi(t);
  return s > n ? null : [s, n];
}
const F = /* @__PURE__ */ bs({
  /** 登录态：null=未登录，对象=/auth/me 的返回 */
  user: null,
  /** 安全职级字典（/admin/levels），用于把数字译成 L0/L1… */
  levels: [],
  departments: [],
  /** 当前视图名 */
  view: "dashboard",
  /** 全局加载遮罩计数（>0 显示忙态） */
  busy: 0,
  /** 未读通知数 */
  unread: 0,
  /** 侧栏系统健康状态 */
  systemOk: null,
  /** 跨视图跳转：通知点击带 ticket_id 时置为工单 id，
   *  TicketsView 挂载/监听后拉取详情并弹窗，随后自行清空。 */
  jumpTicketId: null
}), Ps = /* @__PURE__ */ bs([]);
let Da = 0;
function ee(e, t = "info") {
  const s = ++Da;
  Ps.push({ id: s, text: e, kind: t }), setTimeout(() => {
    const n = Ps.findIndex((l) => l.id === s);
    n >= 0 && Ps.splice(n, 1);
  }, 3200);
}
const Ml = Ce(() => !!F.user);
async function Me(e) {
  F.busy += 1;
  try {
    return await e();
  } finally {
    F.busy -= 1;
  }
}
function Pn() {
  F.user = null, F.unread = 0, nn();
}
const Be = {
  level: () => qt(F.user),
  /** 文档密级名（公开/秘密/机密/绝密） */
  levelName: (e) => Ra(e, F.levels),
  /** 人的层级编号（L0-L3）——文档用 levelName，别混 */
  levelTag: (e) => Na(e),
  maxLevel: () => Gi(F.levels),
  writableRange: () => ja(F.user, F.levels),
  canViewAdmin: () => Yi(F.user),
  canViewTickets: () => Xi(F.user),
  canManageDoc: (e, t, s = !1) => {
    var n;
    return Ma(e, F.user, t, (n = F.user) == null ? void 0 : n.department, s);
  }
}, jl = Ce(() => {
  const e = F.user, t = [{ view: "dashboard", label: "仪表盘", icon: "◧", auditorOnly: !0 }];
  return t.push(
    { view: "documents", label: "文档库", icon: "▤" },
    { view: "chat", label: "智能问答", icon: "◈" },
    { view: "personal", label: "个人中心", icon: "◐" },
    // 系统状态与仪表盘同为运营审计专属：/stats 的运维口径与入库健康度
    // （FAISS/MySQL 一致性）不是普通员工该看的信息面
    { view: "system", label: "系统状态", icon: "◎", auditorOnly: !0 }
  ), Xi(e) && t.push({ view: "tickets", label: "工单中心", icon: "◇" }), Yi(e) && t.push({ view: "admin", label: "管理视图", icon: "◈" }), t.filter((s) => !s.auditorOnly || (e == null ? void 0 : e.is_auditor));
}), Fa = {
  class: "state-icon",
  "aria-hidden": "true"
}, Ua = { class: "state-title" }, La = {
  key: 0,
  class: "state-desc"
}, $e = {
  __name: "StateBox",
  props: {
    kind: { type: String, default: "empty" },
    // empty | loading | error
    title: { type: String, default: "" },
    desc: { type: String, default: "" }
  },
  setup(e) {
    const t = { empty: "◌", loading: "◍", error: "⚠" };
    return (s, n) => (g(), y("div", {
      class: ge(["state-box", `state-box--${e.kind}`])
    }, [
      i("span", Fa, _(t[e.kind] || "◌"), 1),
      i("span", Ua, _(e.title), 1),
      e.desc ? (g(), y("span", La, _(e.desc), 1)) : W("", !0),
      dr(s.$slots, "default")
    ], 2));
  }
}, Va = { class: "stat-grid" }, Ha = { class: "stat-card" }, Ka = { class: "stat-body" }, Ba = { class: "stat-num" }, qa = { class: "stat-card" }, Wa = { class: "stat-body" }, Ja = { class: "stat-num" }, za = {
  key: 0,
  class: "stat-card"
}, Ga = { class: "stat-body" }, Ya = { class: "stat-num" }, Xa = {
  key: 1,
  class: "stat-card"
}, Qa = { class: "stat-body" }, Za = { class: "stat-num" }, eu = { class: "panel" }, tu = { class: "kv-list" }, su = { key: 0 }, nu = { class: "panel" }, lu = {
  key: 1,
  class: "recent-list"
}, iu = { class: "recent-left" }, ou = ["title"], ru = { class: "recent-meta" }, au = {
  key: 0,
  class: "panel"
}, uu = { class: "kv-list" }, cu = {
  key: 1,
  class: "panel"
}, du = { class: "kv-list" }, fu = {
  key: 2,
  class: "hint"
}, pu = {
  __name: "DashboardView",
  setup(e, { expose: t }) {
    const s = /* @__PURE__ */ H(null), n = /* @__PURE__ */ H(""), l = /* @__PURE__ */ H([]), o = [
      ["chunk_size", "分块大小"],
      ["chunk_overlap", "分块重叠"],
      ["top_k_retrieve", "召回 TopK"],
      ["top_k_rerank", "重排 TopK"],
      ["max_context_chars", "上下文上限"],
      ["enable_rerank", "启用重排"],
      ["enable_bm25", "启用 BM25"],
      ["enable_cache", "启用缓存"],
      ["llm_temperature", "温度"],
      ["llm_max_tokens", "最大 Token"]
    ];
    async function a() {
      n.value = "";
      try {
        s.value = await Me(() => G.stats());
      } catch (h) {
        n.value = String(h.message || h);
      }
      try {
        const h = await G.listDocuments(0, 5, "desc");
        l.value = (Array.isArray(h) ? h : h.items) || [];
      } catch {
        l.value = [];
      }
    }
    Ot(a), t({ load: a });
    const r = (h) => typeof h == "boolean" ? h ? "开" : "关" : String(h ?? "—"), c = (h) => (h || "").replace("T", " ").slice(0, 16), f = (h) => ["pdf", "docx", "doc", "xlsx", "txt", "md", "img"].includes(h) ? h : "txt";
    return (h, k) => {
      var R;
      return g(), y("div", null, [
        n.value ? (g(), pe($e, {
          key: 0,
          kind: "error",
          title: "统计加载失败",
          desc: n.value
        }, null, 8, ["desc"])) : s.value ? (g(), y(V, { key: 2 }, [
          i("div", Va, [
            i("div", Ha, [
              k[1] || (k[1] = i("div", { class: "stat-ico c-sapphire" }, "📄", -1)),
              i("div", Ka, [
                i("div", Ba, _(s.value.documents), 1),
                k[0] || (k[0] = i("div", { class: "stat-label" }, "文档总数", -1))
              ])
            ]),
            i("div", qa, [
              k[3] || (k[3] = i("div", { class: "stat-ico c-blue" }, "🧩", -1)),
              i("div", Wa, [
                i("div", Ja, _(s.value.chunks), 1),
                k[2] || (k[2] = i("div", { class: "stat-label" }, "知识分块", -1))
              ])
            ]),
            "vectors" in s.value ? (g(), y("div", za, [
              k[5] || (k[5] = i("div", { class: "stat-ico c-violet" }, "🔢", -1)),
              i("div", Ga, [
                i("div", Ya, _(s.value.vectors ?? "—"), 1),
                k[4] || (k[4] = i("div", { class: "stat-label" }, "向量索引", -1))
              ])
            ])) : W("", !0),
            "bm25" in s.value ? (g(), y("div", Xa, [
              k[7] || (k[7] = i("div", { class: "stat-ico c-teal" }, "🔎", -1)),
              i("div", Qa, [
                i("div", Za, _(s.value.bm25 ?? "—"), 1),
                k[6] || (k[6] = i("div", { class: "stat-label" }, "BM25 索引", -1))
              ])
            ])) : W("", !0)
          ]),
          i("div", eu, [
            k[9] || (k[9] = i("div", { class: "panel-head" }, [
              i("h3", null, "文件类型分布")
            ], -1)),
            i("ul", tu, [
              (g(!0), y(V, null, ne(s.value.file_types || {}, (O, C) => (g(), y("li", { key: C }, [
                i("span", null, _(C), 1),
                i("b", null, _(O), 1)
              ]))), 128)),
              Object.keys(s.value.file_types || {}).length ? W("", !0) : (g(), y("li", su, [...k[8] || (k[8] = [
                i("span", null, "暂无数据", -1)
              ])]))
            ])
          ]),
          i("div", nu, [
            k[10] || (k[10] = i("div", { class: "panel-head" }, [
              i("h3", null, "最近入库")
            ], -1)),
            l.value.length ? (g(), y("div", lu, [
              (g(!0), y(V, null, ne(l.value, (O) => (g(), y("div", {
                key: O.document_id,
                class: "recent-item"
              }, [
                i("div", iu, [
                  i("div", {
                    class: ge(["type-tag", f(String(O.file_type || "").toLowerCase())])
                  }, _(String(O.file_type || "?").slice(0, 3).toUpperCase()), 3),
                  i("div", null, [
                    i("div", {
                      class: "recent-name",
                      title: O.filename || O.title
                    }, _(O.filename || O.title), 9, ou),
                    i("div", ru, _(O.chunk_count ?? "—") + " 分块 · " + _(c(O.created_at)), 1)
                  ])
                ])
              ]))), 128))
            ])) : (g(), pe($e, {
              key: 0,
              kind: "empty",
              title: "暂无文档，请先上传"
            }))
          ]),
          s.value.models ? (g(), y("div", au, [
            k[11] || (k[11] = i("div", { class: "panel-head" }, [
              i("h3", null, "模型配置")
            ], -1)),
            i("ul", uu, [
              (g(!0), y(V, null, ne(s.value.models, (O, C) => (g(), y("li", { key: C }, [
                i("span", null, _(C), 1),
                i("b", null, _(O || "—"), 1)
              ]))), 128))
            ])
          ])) : W("", !0),
          s.value.rag_params ? (g(), y("div", cu, [
            k[12] || (k[12] = i("div", { class: "panel-head" }, [
              i("h3", null, "检索参数")
            ], -1)),
            i("ul", du, [
              (g(), y(V, null, ne(o, ([O, C]) => i("li", { key: O }, [
                i("span", null, _(C), 1),
                i("b", null, _(r(s.value.rag_params[O])), 1)
              ])), 64))
            ])
          ])) : W("", !0),
          (R = ie(F).user) != null && R.is_auditor ? W("", !0) : (g(), y("p", fu, " 模型配置与检索参数属运维敏感信息，仅运营审计可见。 "))
        ], 64)) : (g(), pe($e, {
          key: 1,
          kind: "loading",
          title: "正在加载统计…"
        }))
      ]);
    };
  }
}, hu = { class: "modal active" }, vu = {
  class: "modal-dialog",
  style: { "max-width": "760px" }
}, mu = { class: "modal-head" }, gu = { class: "modal-body" }, _u = {
  class: "info-list",
  style: { "margin-bottom": "18px" }
}, yu = { class: "info-item" }, bu = { class: "info-val" }, ku = { class: "info-item" }, $u = { class: "info-val" }, wu = { class: "info-item" }, xu = { class: "info-val" }, Su = {
  key: 0,
  class: "badge badge--info"
}, Cu = { class: "info-item" }, Tu = { class: "info-val" }, Au = { class: "info-item" }, Ou = { class: "info-val" }, Eu = { class: "info-item" }, Pu = { class: "info-val" }, Iu = { style: { "margin-bottom": "12px", "font-size": "14px" } }, Ru = { class: "chunk-head" }, Nu = { class: "chunk-text" }, Mu = {
  key: 0,
  class: "form-hint"
}, Qi = {
  __name: "DocDetailModal",
  props: {
    /** 文档 id；null 时关闭（v-if 由父组件控制或内部容错） */
    docId: { type: Number, default: null },
    /** 文档密级（数字）；缺省 null 显示 — */
    classification: { type: Number, default: null }
  },
  emits: ["close"],
  setup(e, { emit: t }) {
    const s = e, n = t, l = /* @__PURE__ */ H(null), o = /* @__PURE__ */ H([]), a = /* @__PURE__ */ H("");
    st(
      () => s.docId,
      async (c) => {
        if (l.value = null, o.value = [], a.value = "", c != null)
          try {
            const f = await G.document(c);
            l.value = f.document || f, o.value = f.chunks || [];
          } catch (f) {
            a.value = String(f.message || f);
          }
      },
      { immediate: !0 }
    );
    const r = (c) => (c || "").replace("T", " ").slice(0, 19);
    return (c, f) => (g(), y("div", hu, [
      i("div", {
        class: "modal-mask",
        onClick: f[0] || (f[0] = (h) => n("close"))
      }),
      i("div", vu, [
        i("div", mu, [
          i("h3", null, "文档详情" + _(l.value ? ` · ${l.value.filename}` : ""), 1),
          i("button", {
            class: "modal-close",
            onClick: f[1] || (f[1] = (h) => n("close"))
          }, "✕")
        ]),
        i("div", gu, [
          a.value ? (g(), pe($e, {
            key: 0,
            kind: "error",
            title: "加载失败",
            desc: a.value
          }, null, 8, ["desc"])) : l.value ? (g(), y(V, { key: 2 }, [
            i("div", _u, [
              i("div", yu, [
                f[3] || (f[3] = i("span", { class: "info-key" }, "文件名", -1)),
                i("span", bu, _(l.value.filename), 1)
              ]),
              i("div", ku, [
                f[4] || (f[4] = i("span", { class: "info-key" }, "类型", -1)),
                i("span", $u, _(l.value.file_type), 1)
              ]),
              i("div", wu, [
                f[5] || (f[5] = i("span", { class: "info-key" }, "密级", -1)),
                i("span", xu, [
                  e.classification != null ? (g(), y("span", Su, _(ie(Be).levelName(e.classification)), 1)) : (g(), y(V, { key: 1 }, [
                    nt("—")
                  ], 64))
                ])
              ]),
              i("div", Cu, [
                f[6] || (f[6] = i("span", { class: "info-key" }, "标题", -1)),
                i("span", Tu, _(l.value.title || "—"), 1)
              ]),
              i("div", Au, [
                f[7] || (f[7] = i("span", { class: "info-key" }, "分块数", -1)),
                i("span", Ou, _(l.value.chunk_count), 1)
              ]),
              i("div", Eu, [
                f[8] || (f[8] = i("span", { class: "info-key" }, "入库时间", -1)),
                i("span", Pu, _(r(l.value.created_at)), 1)
              ])
            ]),
            i("h4", Iu, "分块预览（共 " + _(o.value.length) + " 块）", 1),
            o.value.length ? (g(), y(V, { key: 1 }, [
              (g(!0), y(V, null, ne(o.value.slice(0, 50), (h) => (g(), y("div", {
                key: h.chunk_index,
                class: "chunk-item"
              }, [
                i("div", Ru, [
                  i("span", null, "Chunk #" + _(h.chunk_index) + _(h.page ? ` · 第${h.page}页` : "") + _(h.section ? ` · ${h.section}` : ""), 1),
                  i("span", null, "hash: " + _(h.text_hash), 1)
                ]),
                i("div", Nu, _(h.text), 1)
              ]))), 128)),
              o.value.length > 50 ? (g(), y("p", Mu, "仅展示前 50 块，共 " + _(o.value.length) + " 块", 1)) : W("", !0)
            ], 64)) : (g(), pe($e, {
              key: 0,
              kind: "empty",
              title: "无分块数据"
            }))
          ], 64)) : (g(), pe($e, {
            key: 1,
            kind: "loading",
            title: "加载中…"
          })),
          i("button", {
            class: "btn btn-block",
            style: { "margin-top": "12px" },
            onClick: f[2] || (f[2] = (h) => n("close"))
          }, "关闭")
        ])
      ])
    ]));
  }
}, ju = { class: "panel" }, Du = { class: "form-row" }, Fu = { class: "form-item" }, Uu = { class: "form-item" }, Lu = ["value"], Vu = { class: "form-item form-item--full" }, Hu = { class: "dept-chips" }, Ku = ["onClick"], Bu = { class: "form-item" }, qu = ["disabled"], Wu = { value: null }, Ju = ["value"], zu = {
  key: 0,
  class: "form-hint"
}, Gu = ["disabled"], Yu = {
  key: 0,
  style: { "margin-top": "14px" }
}, Xu = {
  class: "upload-summary",
  style: { "margin-bottom": "8px" }
}, Qu = { class: "upload-progress-list" }, Zu = ["title"], ec = { class: "upload-bar" }, tc = { class: "panel" }, sc = { class: "panel-head" }, nc = { class: "panel-actions" }, lc = ["disabled"], ic = {
  key: 2,
  class: "table"
}, oc = ["checked"], rc = ["checked", "onChange"], ac = { class: "row-actions" }, uc = ["onClick"], cc = ["onClick"], dc = ["onClick"], fc = ["onClick"], pc = ["onClick"], hc = {
  key: 3,
  class: "pager"
}, vc = ["disabled"], mc = ["disabled"], gc = {
  key: 0,
  class: "modal active"
}, _c = { class: "modal-dialog" }, yc = { class: "modal-head" }, bc = { key: 0 }, kc = { key: 1 }, $c = { key: 2 }, wc = { key: 3 }, xc = { class: "modal-body" }, Sc = {
  key: 2,
  class: "kv-list"
}, Cc = ["onClick"], Tc = { class: "form-hint" }, Ac = { class: "form-item" }, Oc = ["value"], Ec = { class: "form-item form-item--full" }, Pc = { class: "dept-chips" }, Ic = ["onClick"], Rc = { class: "form-item" }, Nc = ["disabled"], Mc = { value: null }, jc = ["value"], Dc = { class: "form-hint" }, Fc = { class: "form-item" }, Uc = ["disabled"], Lc = { class: "form-item form-item--full" }, Vc = { class: "form-item" }, Hc = ["value"], Kc = { class: "form-item form-item--full" }, Bc = { class: "dept-chips" }, qc = ["onClick"], Wc = { class: "form-item" }, Jc = ["disabled"], zc = { value: null }, Gc = ["value"], Yc = { class: "form-hint" }, Xc = { class: "form-item" }, Qc = ["disabled"], Zc = { class: "kv-list" }, ed = { class: "form-item" }, td = ["disabled"], sd = { value: null }, nd = ["value"], ld = { class: "form-hint" }, id = { class: "form-item" }, Pt = 20, Dl = {
  __name: "DocumentsView",
  setup(e, { expose: t }) {
    const s = /* @__PURE__ */ H([]), n = /* @__PURE__ */ H(0), l = /* @__PURE__ */ H(0), o = /* @__PURE__ */ H(""), a = /* @__PURE__ */ H(""), r = /* @__PURE__ */ H(/* @__PURE__ */ new Set()), c = /* @__PURE__ */ H([]), f = /* @__PURE__ */ H(null), h = /* @__PURE__ */ H([]), k = /* @__PURE__ */ H(null), R = /* @__PURE__ */ H([]), O = /* @__PURE__ */ H(""), C = /* @__PURE__ */ H(!1), j = /* @__PURE__ */ H([]);
    let D = null;
    const se = Ce(() => Be.writableRange()), U = Ce(() => {
      const v = se.value;
      if (!v) return [];
      const [p, d] = v, P = [];
      for (let S = p; S <= d; S += 1) P.push(S);
      return P;
    }), L = Ce(() => {
      var P;
      const v = F.departments || [];
      if (v.length)
        return v.map((S) => ({
          value: S.name,
          label: S.name === "*" ? "不限部门（全员可见）" : S.name
        }));
      const p = ((P = F.user) == null ? void 0 : P.department) || "", d = p ? [{ value: p, label: p }] : [];
      return d.push({ value: "*", label: "不限部门（全员可见）" }), d;
    });
    function I(v) {
      let p = v == null ? void 0 : v.departments;
      if (typeof p == "string")
        try {
          p = JSON.parse(p);
        } catch {
          p = [];
        }
      if (Array.isArray(p) && p.length) return p;
      const d = v == null ? void 0 : v.owner_department;
      return d ? [d] : [];
    }
    function X(v) {
      const p = I(v);
      return p.length ? p.includes("*") ? "不限部门" : p.join(", ") : "—";
    }
    function ve(v) {
      return {
        draft: "草稿（待审批）",
        published: "已发布",
        archived: "已归档",
        expired: "已过期"
      }[v] || v || "—";
    }
    function _e(v) {
      return {
        draft: "badge--warn",
        published: "badge--ok",
        archived: "badge--neutral",
        expired: "badge--err"
      }[v] || "badge--neutral";
    }
    function ye(v, p) {
      const d = v.indexOf(p);
      if (d >= 0) {
        v.splice(d, 1);
        return;
      }
      (p === "*" || v.includes("*")) && (v.length = 0), v.push(p);
    }
    const ot = Ce(() => {
      var v;
      return R.value.length ? "请选择" : f.value == null ? "请先选定密级" : (v = h.value) != null && v.length ? "该组合下无合格审批人" : "请先选定归属部门";
    });
    function we(v) {
      return String(v || "").replace(/[\s\u3000]+/g, "");
    }
    async function Oe() {
      var v, p;
      if (R.value = [], O.value = "", !(f.value == null || !((v = h.value) != null && v.length)))
        try {
          const d = await G.approverCandidates(f.value, h.value), P = Array.isArray(d) ? d : d.items || [], S = new Set(h.value.map(we)), A = h.value.includes("*") ? P : P.filter((K) => S.has(we(K.department)));
          R.value = A;
          const B = P.length - A.length;
          O.value = A.length ? `所选部门内有 ${A.length} 位符合条件（职级≥L${f.value}）：均属 ${(p = d.departments) != null && p.length ? d.departments.join("、") : h.value.join("、")}；任选其一，留空则由系统在这个池内指派` + (B ? `；已剔除 ${B} 位不属于所选部门的候选` : "") : d.reason || "该组合下无合格审批人";
        } catch (d) {
          O.value = `审批人候选加载失败：${d.message || d}`;
        }
    }
    st([f, h], () => {
      k.value = null, Oe();
    }, { deep: !0 });
    function Z(v) {
      c.value = Array.from(v.target.files || []);
    }
    async function q() {
      var P;
      if (!c.value.length) {
        ee("请先选择文件", "error");
        return;
      }
      if (f.value == null) {
        ee("请选择密级", "error");
        return;
      }
      if (!((P = h.value) != null && P.length)) {
        ee("请选择归属部门", "error");
        return;
      }
      C.value = !0;
      const v = [...c.value], p = v.map((S) => ({
        name: S.name,
        status: "pending",
        statusText: "提交中",
        progress: 8
      }));
      j.value.push(...p);
      const d = j.value.slice(-p.length);
      try {
        const S = await Me(() => G.batchUpload(v, f.value, h.value, k.value));
        ee(`已提交 ${v.length} 个文件，入库进行中`, "ok"), ((S == null ? void 0 : S.items) || []).forEach((A, B) => {
          const K = d[B];
          K && (A.status === "failed" ? (K.status = "error", K.statusText = "✗ " + (A.message || "被拒绝"), K.progress = 0) : (K.status = "uploading", K.statusText = "排队中", K.progress = 25));
        }), c.value = [], k.value = null, await re(), S && S.batch_id != null ? Y(S.batch_id, d) : xe();
      } catch (S) {
        d.forEach((A) => {
          A.status === "pending" && (A.status = "error", A.statusText = "✗ " + (S.message || S));
        }), ee(String(S.message || S), "error"), xe();
      } finally {
        C.value = !1;
      }
    }
    async function Y(v, p) {
      for (let d = 0; d < 160; d += 1) {
        await new Promise((A) => setTimeout(A, 1500));
        let P;
        try {
          P = await G.uploadBatch(v);
        } catch {
          p.forEach((A) => {
            A.status === "uploading" && (A.status = "error", A.statusText = "✗ 状态查询失败");
          });
          break;
        }
        const S = Array.isArray(P && P.items) ? P.items : [];
        if (S.forEach((A, B) => {
          const K = p[B];
          K && (A.status === "success" ? (K.status = "success", K.statusText = `✓ ${A.chunk_count} 分块${A.message ? `｜${A.message}` : ""}`, K.progress = 100) : A.status === "skipped" ? (K.status = "success", K.statusText = "重复，已跳过", K.progress = 100) : A.status === "failed" ? (K.status = "error", K.statusText = "✗ " + (A.message || "入库失败"), K.progress = 0) : A.status === "processing" ? (K.status = "uploading", K.statusText = "入库中（Embedding/索引构建）…", K.progress = Math.max(K.progress, 60)) : (K.status = "pending", K.statusText = "排队中"));
        }), P && P.finished) {
          const A = S.filter((K) => K.status === "failed"), B = S.length - A.length;
          ee(`入库完成：成功 ${B}${A.length ? `，失败 ${A.length}` : ""}`, A.length ? "error" : "ok"), A.length && ee(`${A[0].filename}：${A[0].message || "入库失败"}`, "error"), await J(), xe();
          return;
        }
      }
      xe();
    }
    function xe() {
      D && clearTimeout(D), D = setTimeout(() => {
        j.value = j.value.filter((v) => !["success", "error"].includes(v.status));
      }, 8e3);
    }
    async function J() {
      a.value = "";
      try {
        const v = await Me(() => G.listDocuments(l.value, Pt, "asc", o.value));
        s.value = (Array.isArray(v) ? v : v.items) || [], n.value = Number(v.total ?? s.value.length) || s.value.length;
      } catch (v) {
        a.value = String(v.message || v);
      }
    }
    function le(v) {
      l.value = Math.max(0, v), J();
    }
    async function re() {
      await J();
      const v = Math.max(0, Math.floor(Math.max(n.value - 1, 0) / Pt) * Pt);
      v !== l.value && (l.value = v, await J());
    }
    let He = null;
    st(o, () => {
      He && clearTimeout(He), He = setTimeout(() => {
        l.value = 0, J();
      }, 300);
    });
    const rt = Ce(() => {
      const v = o.value.trim().toLowerCase();
      return v ? s.value.filter(
        (p) => String(p.title || "").toLowerCase().includes(v) || String(p.filename || "").toLowerCase().includes(v)
      ) : s.value;
    }), Qe = Ce(
      () => s.value.length > 0 && s.value.every((v) => r.value.has(v.document_id))
    );
    function Ee(v) {
      v.target.checked ? s.value.forEach((p) => r.value.add(p.document_id)) : r.value.clear();
    }
    Ot(J), t({ load: J });
    async function zt(v) {
      try {
        await G.download(v.document_id, v.title);
      } catch (p) {
        ee(String(p.message || p), "error");
      }
    }
    const N = /* @__PURE__ */ H(null), Je = /* @__PURE__ */ H(null);
    function Ze(v) {
      N.value = { type: "versions", doc: v, items: [], loading: !0 }, Et(v);
    }
    async function Et(v) {
      try {
        const p = await G.versions(v.document_id);
        N.value.items = Array.isArray(p) ? p : p.items || [];
      } catch (p) {
        ee(String(p.message || p), "error");
      } finally {
        N.value && (N.value.loading = !1);
      }
    }
    function w(v, p) {
      N.value = {
        type: "rollback",
        doc: v,
        versionNo: p.version_no ?? p.version,
        classification: Number(v.classification) || 0,
        departments: I(v),
        approvers: [],
        approverId: null,
        reason: "",
        hint: ""
      }, z();
    }
    const b = Ce(() => {
      var P, S;
      if (((P = N.value) == null ? void 0 : P.type) !== "rollback") return [];
      const v = Number((S = N.value.doc) == null ? void 0 : S.classification) || 0, p = Be.level(), d = [];
      for (let A = v; A <= p; A += 1) d.push(A);
      return d.length ? d : [v];
    });
    async function z() {
      const v = N.value;
      if (v)
        try {
          const p = await G.approverCandidates(v.classification, v.departments);
          v.approvers = Array.isArray(p) ? p : p.items || [], v.hint = v.approvers.length ? `按目标密级/部门匹配到 ${v.approvers.length} 位可审批人；留空则由系统指派` : p.reason || "该组合下无合格审批人", v.approvers.some((d) => Number(d.id) === Number(v.approverId)) || (v.approverId = null);
        } catch (p) {
          v.hint = `候选加载失败：${p.message || p}`;
        }
    }
    async function u() {
      var p, d;
      const v = N.value;
      if (!v.departments.length) {
        ee("请选择归属部门（空数组会让审批人候选池为空）", "error");
        return;
      }
      try {
        const P = await Me(() => G.rollback(
          v.doc.document_id,
          v.versionNo,
          v.approverId,
          v.reason,
          v.classification,
          v.departments
        )), S = ((p = P == null ? void 0 : P.approver) == null ? void 0 : p.username) || ((d = P == null ? void 0 : P.approver) == null ? void 0 : d.employee_no);
        ee(S ? `已提交回滚申请，待审批通过后生效（审批人：${S}）` : "已提交回滚申请，待审批通过后生效", "ok"), N.value = null, await J();
      } catch (P) {
        ee(String(P.message || P), "error");
      }
    }
    function m(v) {
      N.value = {
        type: "update",
        doc: v,
        newFile: null,
        // 密级选项区间与 writableRange() 一致（[本人职级, 最高密级]，含 L0 公开），
        // 文档现值直接回填，无需抬升。
        classification: Number(v.classification) || 0,
        departments: I(v),
        status: v.status === "archived" ? "archived" : "published",
        reason: "",
        approverId: null,
        approvers: [],
        hint: ""
      }, E();
    }
    function $(v) {
      N.value && (N.value.newFile = (v.target.files || [])[0] || null);
    }
    async function E() {
      const v = N.value;
      if (v)
        try {
          const p = await G.approverCandidates(v.classification, v.departments);
          v.approvers = Array.isArray(p) ? p : p.items || [], v.hint = v.approvers.length ? `匹配到 ${v.approvers.length} 位可审批人` : p.reason || "该组合下无合格审批人", v.approvers.some((d) => Number(d.id) === Number(v.approverId)) || (v.approverId = null);
        } catch (p) {
          v.hint = `候选加载失败：${p.message || p}`;
        }
    }
    st(
      () => N.value ? [N.value.classification, JSON.stringify(N.value.departments)] : null,
      () => {
        var v, p;
        ((v = N.value) == null ? void 0 : v.type) === "update" ? E() : ((p = N.value) == null ? void 0 : p.type) === "rollback" && z();
      }
    );
    async function x() {
      var p, d, P, S;
      const v = N.value;
      if ((v.reason || "").trim().length < 5) {
        ee("变更原因至少 5 个字", "error");
        return;
      }
      try {
        if (v.newFile) {
          const A = await Me(() => G.uploadVersion(
            v.doc.document_id,
            v.newFile,
            v.classification,
            v.departments,
            v.approverId,
            v.reason.trim()
          )), B = (A == null ? void 0 : A.auto_approval) || {};
          if (B.auto_submitted) {
            const K = ((p = B.approver) == null ? void 0 : p.username) || ((d = B.approver) == null ? void 0 : d.employee_no) || "系统指派";
            ee(`新版本已上传，已提交发布审批（审批人：${K}）`, "ok");
          } else
            ee(`新版本已上传，但未提交审批：${B.reason || "原因未知"}`, "error");
        } else {
          const A = await Me(
            () => G._post(`/governance/documents/${v.doc.document_id}/requests`, {
              classification: v.classification,
              departments: v.departments,
              status: v.status,
              reason: v.reason.trim(),
              ...v.approverId != null ? { approver_id: Number(v.approverId) } : {}
            })
          ), B = ((P = A == null ? void 0 : A.approver) == null ? void 0 : P.username) || ((S = A == null ? void 0 : A.approver) == null ? void 0 : S.employee_no);
          ee(B ? `变更申请已提交，审批人：${B}` : "变更申请已提交，待审批", "ok");
        }
        N.value = null, await J();
      } catch (A) {
        ee(String(A.message || A), "error");
      }
    }
    async function T(v) {
      const p = s.value.filter((d) => v.includes(d.document_id));
      if (!p.length) {
        ee("所选文档已失效，请刷新后重试", "error");
        return;
      }
      N.value = {
        type: "delete",
        ids: v,
        docs: p,
        // 审批所需职级取批次内最高密级（审批人必须能读取批次里每一篇）
        level: Math.max(...p.map((d) => Number(d.classification) || 0)),
        reason: "",
        approverId: null,
        approvers: [],
        hint: ""
      };
      try {
        const d = await G.approverCandidates(N.value.level, I(p[0]));
        N.value.approvers = Array.isArray(d) ? d : d.items || [], N.value.hint = N.value.approvers.length ? `匹配到 ${N.value.approvers.length} 位可审批人` : d.reason || "该组合下无合格审批人";
      } catch (d) {
        N.value.hint = `候选加载失败：${d.message || d}`;
      }
    }
    async function M() {
      const v = N.value;
      if ((v.reason || "").trim().length < 5) {
        ee("删除原因至少 5 个字", "error");
        return;
      }
      try {
        await Me(
          () => G.createTicket(
            "doc_batch_delete",
            { doc_ids: v.ids.map(String), reason: v.reason.trim() },
            v.approverId != null ? Number(v.approverId) : null
          )
        ), ee("删除申请已提交，待审批", "ok"), r.value.clear(), N.value = null;
      } catch (p) {
        ee(String(p.message || p), "error");
      }
    }
    return (v, p) => (g(), y("div", null, [
      i("div", ju, [
        p[25] || (p[25] = i("div", { class: "panel-head" }, [
          i("h3", null, "上传文档")
        ], -1)),
        i("div", Du, [
          i("div", Fu, [
            p[19] || (p[19] = i("label", null, "文件（可多选）", -1)),
            i("input", {
              class: "input",
              type: "file",
              multiple: "",
              onChange: Z
            }, null, 32)
          ]),
          i("div", Uu, [
            p[21] || (p[21] = i("label", null, "密级", -1)),
            ke(i("select", {
              "onUpdate:modelValue": p[0] || (p[0] = (d) => f.value = d),
              class: "input"
            }, [
              p[20] || (p[20] = i("option", { value: null }, "请选择", -1)),
              (g(!0), y(V, null, ne(U.value, (d) => (g(), y("option", {
                key: d,
                value: d
              }, _(ie(Be).levelName(d)), 9, Lu))), 128))
            ], 512), [
              [wt, f.value]
            ])
          ]),
          i("div", Vu, [
            p[22] || (p[22] = i("label", null, "归属部门（点选，可多选）", -1)),
            i("div", Hu, [
              (g(!0), y(V, null, ne(L.value, (d) => (g(), y("span", {
                key: d.value,
                class: ge(["dept-chip", { "dept-chip--on": h.value.includes(d.value) }]),
                onClick: (P) => ye(h.value, d.value)
              }, _(d.label), 11, Ku))), 128))
            ]),
            p[23] || (p[23] = i("p", { class: "form-hint" }, " 归属部门即「谁能看到、由谁审」：只勾选某部门→仅该部门可读、且审批人只从该部门产生； 选「不限部门」→全员可读、审批人也不再限部门。密级只决定可读/可审的职级下限。 ", -1))
          ]),
          i("div", Bu, [
            p[24] || (p[24] = i("label", null, "审批人", -1)),
            ke(i("select", {
              "onUpdate:modelValue": p[1] || (p[1] = (d) => k.value = d),
              class: "input",
              disabled: !R.value.length
            }, [
              i("option", Wu, _(ot.value), 1),
              (g(!0), y(V, null, ne(R.value, (d) => (g(), y("option", {
                key: d.id,
                value: d.id
              }, _(d.username || d.name) + "（" + _(d.department) + " L" + _(d.security_level) + "） ", 9, Ju))), 128))
            ], 8, qu), [
              [wt, k.value]
            ]),
            O.value ? (g(), y("p", zu, _(O.value), 1)) : W("", !0)
          ])
        ]),
        i("button", {
          class: "btn btn-primary",
          disabled: C.value,
          onClick: q
        }, _(C.value ? "上传中…" : "开始上传"), 9, Gu),
        j.value.length ? (g(), y("div", Yu, [
          i("div", Xu, " 入库进度：" + _(j.value.filter((d) => ["success", "error"].includes(d.status)).length) + " / " + _(j.value.length), 1),
          i("div", Qu, [
            (g(!0), y(V, null, ne(j.value, (d, P) => (g(), y("div", {
              key: P,
              class: "upload-item"
            }, [
              i("div", {
                class: "upload-name",
                title: d.name
              }, _(d.name), 9, Zu),
              i("div", ec, [
                i("div", {
                  class: "upload-bar-fill",
                  style: es({ width: (d.progress || 0) + "%" })
                }, null, 4)
              ]),
              i("div", {
                class: ge(["upload-status", d.status])
              }, _(d.statusText), 3)
            ]))), 128))
          ])
        ])) : W("", !0)
      ]),
      i("div", tc, [
        i("div", sc, [
          i("h3", null, "文档列表（" + _(n.value) + _(o.value.trim() ? "，按关键字搜索全库" : "，新文档在末页") + "）", 1),
          i("div", nc, [
            ke(i("input", {
              "onUpdate:modelValue": p[2] || (p[2] = (d) => o.value = d),
              class: "input",
              placeholder: "搜索标题 / 文件名（全库）"
            }, null, 512), [
              [ze, o.value]
            ]),
            i("button", {
              class: "btn",
              onClick: J
            }, "刷新"),
            i("button", {
              class: "btn btn-danger",
              disabled: !r.value.size,
              onClick: p[3] || (p[3] = (d) => T([...r.value]))
            }, " 批量删除（" + _(r.value.size) + "） ", 9, lc)
          ])
        ]),
        a.value ? (g(), pe($e, {
          key: 0,
          kind: "error",
          title: "加载失败",
          desc: a.value
        }, null, 8, ["desc"])) : !rt.value.length && !ie(F).busy ? (g(), pe($e, {
          key: 1,
          kind: "empty",
          title: o.value.trim() ? "没有匹配的文档" : "暂无文档",
          desc: o.value.trim() ? "已搜全库（标题 + 文件名），换个关键字试试" : ""
        }, null, 8, ["title", "desc"])) : (g(), y("table", ic, [
          i("thead", null, [
            i("tr", null, [
              i("th", null, [
                i("input", {
                  type: "checkbox",
                  checked: Qe.value,
                  onChange: Ee
                }, null, 40, oc)
              ]),
              p[26] || (p[26] = i("th", null, "标题", -1)),
              p[27] || (p[27] = i("th", null, "密级", -1)),
              p[28] || (p[28] = i("th", null, "归属部门", -1)),
              p[29] || (p[29] = i("th", null, "状态", -1)),
              p[30] || (p[30] = i("th", null, "类型", -1)),
              p[31] || (p[31] = i("th", null, "分块", -1)),
              p[32] || (p[32] = i("th", null, "操作", -1))
            ])
          ]),
          i("tbody", null, [
            (g(!0), y(V, null, ne(rt.value, (d) => (g(), y("tr", {
              key: d.document_id
            }, [
              i("td", null, [
                i("input", {
                  type: "checkbox",
                  checked: r.value.has(d.document_id),
                  onChange: (P) => P.target.checked ? r.value.add(d.document_id) : r.value.delete(d.document_id)
                }, null, 40, rc)
              ]),
              i("td", null, _(d.title), 1),
              i("td", null, _(ie(Be).levelName(d.classification)), 1),
              i("td", null, _(X(d)), 1),
              i("td", null, [
                i("span", {
                  class: ge(["badge", _e(d.status)])
                }, _(ve(d.status)), 3)
              ]),
              i("td", null, _(d.file_type), 1),
              i("td", null, _(d.chunk_count ?? "—"), 1),
              i("td", ac, [
                i("button", {
                  class: "btn",
                  onClick: (P) => Je.value = { id: d.document_id, classification: Number(d.classification) || 0 }
                }, "详情", 8, uc),
                i("button", {
                  class: "btn",
                  onClick: (P) => zt(d)
                }, "下载", 8, cc),
                i("button", {
                  class: "btn",
                  onClick: (P) => Ze(d)
                }, "版本历史", 8, dc),
                i("button", {
                  class: "btn",
                  onClick: (P) => m(d)
                }, "申请更新", 8, fc),
                i("button", {
                  class: "btn btn-danger",
                  onClick: (P) => T([d.document_id])
                }, "删除", 8, pc)
              ])
            ]))), 128))
          ])
        ])),
        n.value > Pt ? (g(), y("div", hc, [
          i("button", {
            class: "btn",
            disabled: l.value === 0,
            onClick: p[4] || (p[4] = (d) => le(l.value - Pt))
          }, "上一页", 8, vc),
          i("span", null, _(l.value + 1) + "–" + _(Math.min(l.value + Pt, n.value)) + " / " + _(n.value), 1),
          i("button", {
            class: "btn",
            disabled: l.value + Pt >= n.value,
            onClick: p[5] || (p[5] = (d) => le(l.value + Pt))
          }, "下一页", 8, mc)
        ])) : W("", !0)
      ]),
      N.value ? (g(), y("div", gc, [
        i("div", {
          class: "modal-mask",
          onClick: p[6] || (p[6] = (d) => N.value = null)
        }),
        i("div", _c, [
          i("div", yc, [
            N.value.type === "versions" ? (g(), y("h3", bc, "版本历史 · " + _(N.value.doc.title), 1)) : N.value.type === "update" ? (g(), y("h3", kc, "申请更新 · " + _(N.value.doc.title), 1)) : N.value.type === "rollback" ? (g(), y("h3", $c, "申请回滚 · " + _(N.value.doc.title), 1)) : (g(), y("h3", wc, "申请删除（" + _(N.value.ids.length) + " 篇）", 1)),
            i("button", {
              class: "modal-close",
              onClick: p[7] || (p[7] = (d) => N.value = null)
            }, "✕")
          ]),
          i("div", xc, [
            N.value.type === "versions" ? (g(), y(V, { key: 0 }, [
              N.value.loading ? (g(), pe($e, {
                key: 0,
                kind: "loading",
                title: "加载中…"
              })) : N.value.items.length ? (g(), y("ul", Sc, [
                (g(!0), y(V, null, ne(N.value.items, (d) => (g(), y("li", {
                  key: d.version_no ?? d.version
                }, [
                  i("span", null, "#" + _(d.version_no ?? d.version) + " · " + _(d.created_at || ""), 1),
                  i("button", {
                    class: "btn",
                    onClick: (P) => w(N.value.doc, d)
                  }, "申请回滚", 8, Cc)
                ]))), 128))
              ])) : (g(), pe($e, {
                key: 1,
                kind: "empty",
                title: "暂无历史版本"
              }))
            ], 64)) : N.value.type === "rollback" ? (g(), y(V, { key: 1 }, [
              i("p", Tc, [
                nt(" 将把《" + _(N.value.doc.title) + "》回滚到历史版本 ", 1),
                i("b", null, "v" + _(N.value.versionNo), 1),
                p[33] || (p[33] = nt("。 审批通过后才生效，且不会改写历史版本本身——系统会用该版本的内容生成一个新版本。 ", -1))
              ]),
              i("div", Ac, [
                p[34] || (p[34] = i("label", null, "目标密级", -1)),
                ke(i("select", {
                  "onUpdate:modelValue": p[8] || (p[8] = (d) => N.value.classification = d),
                  class: "input"
                }, [
                  (g(!0), y(V, null, ne(b.value, (d) => (g(), y("option", {
                    key: d,
                    value: d
                  }, _(ie(Be).levelName(d)), 9, Oc))), 128))
                ], 512), [
                  [wt, N.value.classification]
                ]),
                p[35] || (p[35] = i("p", { class: "form-hint" }, " 回滚只恢复内容，密级由你声明、审批人按此复核；可维持或抬高， 降密请走「申请更新」单独审批。 ", -1))
              ]),
              i("div", Ec, [
                p[36] || (p[36] = i("label", null, "归属部门（点选，可多选）", -1)),
                i("div", Pc, [
                  (g(!0), y(V, null, ne(L.value, (d) => (g(), y("span", {
                    key: d.value,
                    class: ge(["dept-chip", { "dept-chip--on": N.value.departments.includes(d.value) }]),
                    onClick: (P) => ye(N.value.departments, d.value)
                  }, _(d.label), 11, Ic))), 128))
                ])
              ]),
              i("div", Rc, [
                p[37] || (p[37] = i("label", null, "审批人", -1)),
                ke(i("select", {
                  "onUpdate:modelValue": p[9] || (p[9] = (d) => N.value.approverId = d),
                  class: "input",
                  disabled: !N.value.approvers.length
                }, [
                  i("option", Mc, _(N.value.approvers.length ? "请选择（留空则系统指派）" : "无合格审批人"), 1),
                  (g(!0), y(V, null, ne(N.value.approvers, (d) => (g(), y("option", {
                    key: d.id,
                    value: d.id
                  }, _(d.username || d.name) + "（" + _(d.department) + " L" + _(d.security_level) + "） ", 9, jc))), 128))
                ], 8, Nc), [
                  [wt, N.value.approverId]
                ]),
                i("p", Dc, _(N.value.hint), 1)
              ]),
              i("div", Fc, [
                p[38] || (p[38] = i("label", null, "回滚原因（可选）", -1)),
                ke(i("textarea", {
                  "onUpdate:modelValue": p[10] || (p[10] = (d) => N.value.reason = d),
                  class: "input",
                  rows: "3"
                }, null, 512), [
                  [ze, N.value.reason]
                ])
              ]),
              i("button", {
                class: "btn btn-primary btn-block",
                disabled: ie(F).busy,
                onClick: u
              }, " 提交回滚申请 ", 8, Uc)
            ], 64)) : N.value.type === "update" ? (g(), y(V, { key: 2 }, [
              i("div", Lc, [
                p[39] || (p[39] = i("label", null, "新版本文件（可选）", -1)),
                i("input", {
                  type: "file",
                  class: "input",
                  onChange: p[11] || (p[11] = (d) => $(d))
                }, null, 32),
                p[40] || (p[40] = i("p", { class: "form-hint" }, " 选择后将替换文档内容并生成新版本（doc_id 不变、版本号自增，旧版本自动归档、可在版本历史中回滚）； 文件名无需与原文件相同。不选文件则仅提交密级/部门变更申请。 ", -1))
              ]),
              i("div", Vc, [
                p[41] || (p[41] = i("label", null, "密级", -1)),
                ke(i("select", {
                  "onUpdate:modelValue": p[12] || (p[12] = (d) => N.value.classification = d),
                  class: "input"
                }, [
                  (g(!0), y(V, null, ne(U.value, (d) => (g(), y("option", {
                    key: d,
                    value: d
                  }, _(ie(Be).levelName(d)), 9, Hc))), 128))
                ], 512), [
                  [wt, N.value.classification]
                ])
              ]),
              i("div", Kc, [
                p[42] || (p[42] = i("label", null, "归属部门（点选，可多选）", -1)),
                i("div", Bc, [
                  (g(!0), y(V, null, ne(L.value, (d) => (g(), y("span", {
                    key: d.value,
                    class: ge(["dept-chip", { "dept-chip--on": N.value.departments.includes(d.value) }]),
                    onClick: (P) => ye(N.value.departments, d.value)
                  }, _(d.label), 11, qc))), 128))
                ]),
                p[43] || (p[43] = i("p", { class: "form-hint" }, " 改成某部门后，原部门将不再可读；选「不限部门」则全员可读。 ", -1))
              ]),
              i("div", Wc, [
                p[44] || (p[44] = i("label", null, "审批人", -1)),
                ke(i("select", {
                  "onUpdate:modelValue": p[13] || (p[13] = (d) => N.value.approverId = d),
                  class: "input",
                  disabled: !N.value.approvers.length
                }, [
                  i("option", zc, _(N.value.approvers.length ? "请选择（留空则系统指派）" : "无合格审批人"), 1),
                  (g(!0), y(V, null, ne(N.value.approvers, (d) => (g(), y("option", {
                    key: d.id,
                    value: d.id
                  }, _(d.username || d.name) + "（" + _(d.department) + " L" + _(d.security_level) + "） ", 9, Gc))), 128))
                ], 8, Jc), [
                  [wt, N.value.approverId]
                ]),
                i("p", Yc, _(N.value.hint), 1)
              ]),
              i("div", Xc, [
                p[45] || (p[45] = i("label", null, "变更原因（≥5 字）", -1)),
                ke(i("textarea", {
                  "onUpdate:modelValue": p[14] || (p[14] = (d) => N.value.reason = d),
                  class: "input",
                  rows: "3"
                }, null, 512), [
                  [ze, N.value.reason]
                ])
              ]),
              i("button", {
                class: "btn btn-primary btn-block",
                disabled: ie(F).busy,
                onClick: x
              }, _(N.value.newFile ? "上传新版本" : "提交申请"), 9, Qc)
            ], 64)) : (g(), y(V, { key: 3 }, [
              p[48] || (p[48] = i("p", {
                class: "form-hint",
                style: { color: "var(--c-err)" }
              }, " ⚠️ 审批通过后系统将永久删除这些文档及其分块、密级记录与向量索引，不可撤销。 ", -1)),
              i("ul", Zc, [
                (g(!0), y(V, null, ne(N.value.docs, (d) => (g(), y("li", {
                  key: d.document_id
                }, [
                  i("span", null, "#" + _(d.document_id) + " " + _(d.title), 1),
                  i("b", null, _(ie(Be).levelName(d.classification)), 1)
                ]))), 128))
              ]),
              i("div", ed, [
                p[46] || (p[46] = i("label", null, "审批人", -1)),
                ke(i("select", {
                  "onUpdate:modelValue": p[15] || (p[15] = (d) => N.value.approverId = d),
                  class: "input",
                  disabled: !N.value.approvers.length
                }, [
                  i("option", sd, _(N.value.approvers.length ? "请选择（留空则系统指派）" : "无合格审批人"), 1),
                  (g(!0), y(V, null, ne(N.value.approvers, (d) => (g(), y("option", {
                    key: d.id,
                    value: d.id
                  }, _(d.username || d.name) + "（" + _(d.department) + " L" + _(d.security_level) + "） ", 9, nd))), 128))
                ], 8, td), [
                  [wt, N.value.approverId]
                ]),
                i("p", ld, _(N.value.hint), 1)
              ]),
              i("div", id, [
                p[47] || (p[47] = i("label", null, "删除原因（≥5 字）", -1)),
                ke(i("textarea", {
                  "onUpdate:modelValue": p[16] || (p[16] = (d) => N.value.reason = d),
                  class: "input",
                  rows: "3"
                }, null, 512), [
                  [ze, N.value.reason]
                ])
              ]),
              i("button", {
                class: "btn btn-danger btn-block",
                onClick: M
              }, "提交删除申请")
            ], 64)),
            i("button", {
              class: "btn btn-block",
              style: { "margin-top": "8px" },
              onClick: p[17] || (p[17] = (d) => N.value = null)
            }, "关闭")
          ])
        ])
      ])) : W("", !0),
      Je.value ? (g(), pe(Qi, {
        key: 1,
        "doc-id": Je.value.id,
        classification: Je.value.classification,
        onClose: p[18] || (p[18] = (d) => Je.value = null)
      }, null, 8, ["doc-id", "classification"])) : W("", !0)
    ]));
  }
};
function od(e) {
  return String(e ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
const rd = /^(https?:|mailto:|\/|#)/i;
function ls(e) {
  return e.replace(/`([^`]+)`/g, (t, s) => `<code>${s}</code>`).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>").replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (t, s, n) => rd.test(n) ? `<a href="${n}" target="_blank" rel="noopener noreferrer">${s}</a>` : s);
}
function ad(e) {
  const t = String(e ?? ""), n = od(t).split(`
`), l = [];
  let o = null, a = !1, r = [];
  const c = () => {
    o && (l.push(`</${o}>`), o = null);
  };
  for (const f of n) {
    const h = f.replace(/\s+$/, "");
    if (/^```/.test(h)) {
      a ? (l.push(`<pre><code>${r.join(`
`)}</code></pre>`), r = [], a = !1) : (c(), a = !0);
      continue;
    }
    if (a) {
      r.push(f);
      continue;
    }
    const k = /^(#{1,4})\s+(.*)$/.exec(h);
    if (k) {
      c(), l.push(`<h${k[1].length}>${ls(k[2])}</h${k[1].length}>`);
      continue;
    }
    const R = /^&gt;\s?(.*)$/.exec(h);
    if (R) {
      c(), l.push(`<blockquote>${ls(R[1])}</blockquote>`);
      continue;
    }
    if (/^---+$/.test(h.trim())) {
      c(), l.push("<hr>");
      continue;
    }
    const O = /^\s*[-*]\s+(.*)$/.exec(h);
    if (O) {
      o !== "ul" && (c(), l.push("<ul>"), o = "ul"), l.push(`<li>${ls(O[1])}</li>`);
      continue;
    }
    const C = /^\s*\d+[.、]\s*(.*)$/.exec(h);
    if (C) {
      o !== "ol" && (c(), l.push("<ol>"), o = "ol"), l.push(`<li>${ls(C[1])}</li>`);
      continue;
    }
    if (!h.trim()) {
      c();
      continue;
    }
    c(), l.push(`<p>${ls(h)}</p>`);
  }
  return a && r.length && l.push(`<pre><code>${r.join(`
`)}</code></pre>`), c(), l.join(`
`);
}
const ud = { class: "chat-layout" }, cd = { class: "conv-panel" }, dd = { class: "conv-list" }, fd = {
  key: 0,
  class: "conv-empty"
}, pd = ["onClick"], hd = { class: "conv-title" }, vd = { class: "conv-meta" }, md = { class: "fb" }, gd = { class: "chat-panel" }, _d = {
  key: 0,
  class: "msg msg-system"
}, yd = { class: "msg-avatar" }, bd = { class: "msg-content" }, kd = {
  key: 0,
  class: "msg-bubble"
}, $d = ["innerHTML"], wd = {
  key: 2,
  class: "msg-actions"
}, xd = ["onClick"], Sd = ["onClick"], Cd = { class: "chat-input-bar" }, Td = ["onKeydown"], Ad = ["disabled"], Od = { class: "sources-panel" }, Ed = { class: "sources-head" }, Pd = { class: "sources-count" }, Id = { class: "sources-list" }, Rd = {
  key: 0,
  class: "conv-empty"
}, Nd = { class: "source-title" }, Md = ["onClick"], jd = { key: 1 }, Dd = {
  key: 0,
  class: "source-meta"
}, Fd = {
  key: 1,
  class: "source-snippet"
}, Ud = {
  __name: "ChatView",
  setup(e) {
    const t = /* @__PURE__ */ H([]), s = /* @__PURE__ */ H(null), n = /* @__PURE__ */ H([]), l = /* @__PURE__ */ H(""), o = /* @__PURE__ */ H([]), a = /* @__PURE__ */ H(!1), r = /* @__PURE__ */ H(""), c = /* @__PURE__ */ H(null), f = /* @__PURE__ */ H(0);
    async function h() {
      await Ns();
      const U = c.value;
      U && (U.scrollTop = U.scrollHeight);
    }
    st(f, h);
    async function k() {
      try {
        const U = await G.conversations(50);
        t.value = Array.isArray(U) ? U : U.items || [];
      } catch (U) {
        r.value = String(U.message || U);
      }
    }
    async function R(U) {
      s.value = U, n.value = [], o.value = [];
      try {
        const L = await Me(() => G.conversationHistory(U, 100)), I = Array.isArray(L) ? L : L.items || L.messages || [], X = [];
        for (const ve of I)
          ve.question && X.push({ role: "user", content: ve.question, id: null }), ve.answer && X.push({ role: "assistant", content: ve.answer, id: ve.id ?? null });
        n.value = X, await h();
      } catch (L) {
        ee(String(L.message || L), "error");
      }
    }
    function O() {
      s.value = null, n.value = [], o.value = [];
    }
    async function C() {
      const U = l.value.trim();
      if (!U || a.value) return;
      l.value = "", a.value = !0, n.value.push({ role: "user", content: U }), n.value.push({ role: "assistant", content: "", id: null });
      const L = n.value.length - 1;
      let I = "";
      try {
        await G.askStreamIn(U, s.value, (X) => {
          X.type === "chunk" ? (n.value[L].content += X.content ?? "", f.value += 1) : X.type === "done" ? (o.value = X.sources || [], n.value[L].id = X.message_id ?? null, X.session_id && (s.value = X.session_id)) : X.type === "error" && (I = X.message || "服务异常");
        }), await k();
      } catch (X) {
        I = I || String(X.message || X);
      } finally {
        a.value = !1, await Ns();
      }
      I && (ee(`问答失败：${I}`, "error"), n.value[L].content || (n.value[L].content = `（生成失败：${I}）`));
    }
    async function j(U, L) {
      if (U.id == null) {
        ee("该回答尚无消息 ID，无法反馈", "error");
        return;
      }
      try {
        await G.feedback(U.id, L, ""), ee("感谢反馈", "ok");
      } catch (I) {
        ee(String(I.message || I), "error");
      }
    }
    const D = (U) => {
      const L = Number(U);
      return Number.isInteger(L) && L > 0 ? L : null;
    };
    async function se(U) {
      const L = D(U.document_id);
      if (L)
        try {
          await G.download(L, U.title);
        } catch (I) {
          ee(String(I.message || I), "error");
        }
    }
    return Ot(k), (U, L) => (g(), y("div", ud, [
      i("aside", cd, [
        i("div", { class: "conv-head" }, [
          i("button", {
            class: "btn btn-primary btn-block",
            onClick: O
          }, "新建对话")
        ]),
        i("div", dd, [
          t.value.length ? W("", !0) : (g(), y("div", fd, "暂无历史")),
          (g(!0), y(V, null, ne(t.value, (I) => (g(), y("div", {
            key: I.session_id,
            class: ge(["conv-item", { active: I.session_id === s.value }]),
            onClick: (X) => R(I.session_id)
          }, [
            i("div", hd, _(I.summary || I.session_id), 1),
            i("div", vd, [
              i("span", null, _(I.last_time || ""), 1),
              i("span", md, _(I.msg_count ?? 0) + " 条", 1)
            ])
          ], 10, pd))), 128))
        ])
      ]),
      i("section", gd, [
        i("div", {
          ref_key: "msgBox",
          ref: c,
          class: "chat-messages"
        }, [
          n.value.length ? W("", !0) : (g(), y("div", _d, [...L[1] || (L[1] = [
            i("div", { class: "msg-avatar" }, "💡", -1),
            i("div", { class: "msg-content" }, [
              i("div", { class: "msg-bubble" }, [
                nt(" 👋 你好！我是基于知识库的问答助手。请输入问题，我会从已入库的文档中检索并回答，同时给出参考来源。 "),
                i("br"),
                i("small", null, "支持多轮对话上下文、流式输出、Markdown 渲染与答案反馈。")
              ])
            ], -1)
          ])])),
          (g(!0), y(V, null, ne(n.value, (I, X) => (g(), y("div", {
            key: X,
            class: ge(["msg", I.role === "user" ? "msg-user" : "msg-bot"])
          }, [
            i("div", yd, _(I.role === "user" ? "🧑" : "🤖"), 1),
            i("div", bd, [
              I.role === "user" ? (g(), y("div", kd, _(I.content), 1)) : (g(), y("div", {
                key: 1,
                class: "msg-bubble",
                innerHTML: ie(ad)(I.content)
              }, null, 8, $d)),
              I.role === "assistant" && I.id != null ? (g(), y("div", wd, [
                i("button", {
                  class: "msg-action",
                  title: "答案有用",
                  onClick: (ve) => j(I, 1)
                }, "👍", 8, xd),
                i("button", {
                  class: "msg-action dislike",
                  title: "答案无用",
                  onClick: (ve) => j(I, -1)
                }, "👎", 8, Sd)
              ])) : W("", !0)
            ])
          ], 2))), 128))
        ], 512),
        i("div", Cd, [
          ke(i("textarea", {
            "onUpdate:modelValue": L[0] || (L[0] = (I) => l.value = I),
            rows: "2",
            placeholder: "输入问题，回车发送",
            onKeydown: Sa(qi(C, ["exact", "prevent"]), ["enter"])
          }, null, 40, Td), [
            [ze, l.value]
          ]),
          i("button", {
            class: "btn btn-primary",
            disabled: a.value,
            onClick: C
          }, _(a.value ? "生成中…" : "发送"), 9, Ad)
        ])
      ]),
      i("aside", Od, [
        i("div", Ed, [
          L[2] || (L[2] = i("span", null, "参考来源", -1)),
          i("span", Pd, _(o.value.length), 1)
        ]),
        i("div", Id, [
          o.value.length ? W("", !0) : (g(), y("div", Rd, "暂无来源")),
          (g(!0), y(V, null, ne(o.value, (I, X) => (g(), y("div", {
            key: X,
            class: ge(["source-card", { "source-card--clickable": D(I.document_id) }])
          }, [
            i("div", Nd, [
              nt(_(X + 1) + ". ", 1),
              D(I.document_id) ? (g(), y("a", {
                key: 0,
                class: "source-link",
                href: "javascript:void(0)",
                onClick: (ve) => se(I)
              }, _(I.title || "未命名文档"), 9, Md)) : (g(), y("span", jd, _(I.title || "未命名文档"), 1))
            ]),
            I.page ? (g(), y("div", Dd, "第 " + _(I.page) + " 页", 1)) : W("", !0),
            I.snippet ? (g(), y("div", Fd, _(I.snippet), 1)) : W("", !0)
          ], 2))), 128))
        ])
      ])
    ]));
  }
}, Ld = { class: "panel" }, Vd = { class: "kv-list" }, Hd = { class: "panel" }, Kd = {
  key: 2,
  class: "kv-list"
}, Bd = { class: "panel" }, qd = { class: "form-row" }, Wd = { class: "form-item" }, Jd = { class: "form-item" }, zd = { class: "form-item" }, Gd = {
  __name: "PersonalView",
  setup(e) {
    const t = /* @__PURE__ */ H(null), s = /* @__PURE__ */ H(""), n = /* @__PURE__ */ H(""), l = /* @__PURE__ */ H(""), o = /* @__PURE__ */ H("");
    async function a() {
      s.value = "";
      try {
        t.value = await Me(() => G.knowledgePersonalStats());
      } catch (c) {
        s.value = String(c.message || c);
      }
    }
    async function r() {
      if (l.value.length < 6) {
        ee("新密码至少 6 位", "error");
        return;
      }
      if (l.value !== o.value) {
        ee("两次输入不一致", "error");
        return;
      }
      try {
        await Me(() => G.changePassword(n.value, l.value)), ee("密码已修改", "ok"), n.value = l.value = o.value = "";
      } catch (c) {
        ee(String(c.message || c), "error");
      }
    }
    return Ot(a), (c, f) => {
      var h, k, R, O;
      return g(), y("div", null, [
        i("div", Ld, [
          f[8] || (f[8] = i("div", { class: "panel-head" }, [
            i("h3", null, "我的信息")
          ], -1)),
          i("ul", Vd, [
            i("li", null, [
              f[3] || (f[3] = i("span", null, "工号", -1)),
              i("b", null, _((h = ie(F).user) == null ? void 0 : h.employee_no), 1)
            ]),
            i("li", null, [
              f[4] || (f[4] = i("span", null, "姓名", -1)),
              i("b", null, _((k = ie(F).user) == null ? void 0 : k.username), 1)
            ]),
            i("li", null, [
              f[5] || (f[5] = i("span", null, "部门", -1)),
              i("b", null, _(((R = ie(F).user) == null ? void 0 : R.department) || "—"), 1)
            ]),
            i("li", null, [
              f[6] || (f[6] = i("span", null, "安全职级", -1)),
              i("b", null, _(ie(Be).levelTag(ie(Be).level())), 1)
            ]),
            i("li", null, [
              f[7] || (f[7] = i("span", null, "运营审计", -1)),
              i("b", null, _((O = ie(F).user) != null && O.is_auditor ? "是" : "否"), 1)
            ])
          ])
        ]),
        i("div", Hd, [
          f[9] || (f[9] = i("div", { class: "panel-head" }, [
            i("h3", null, "我的统计")
          ], -1)),
          s.value ? (g(), pe($e, {
            key: 0,
            kind: "error",
            title: "加载失败",
            desc: s.value
          }, null, 8, ["desc"])) : t.value ? (g(), y("ul", Kd, [
            (g(!0), y(V, null, ne(t.value, (C, j) => (g(), y("li", { key: j }, [
              i("span", null, _(j), 1),
              i("b", null, _(C), 1)
            ]))), 128))
          ])) : (g(), pe($e, {
            key: 1,
            kind: "loading",
            title: "加载中…"
          }))
        ]),
        i("div", Bd, [
          f[13] || (f[13] = i("div", { class: "panel-head" }, [
            i("h3", null, "修改密码")
          ], -1)),
          i("div", qd, [
            i("div", Wd, [
              f[10] || (f[10] = i("label", null, "原密码", -1)),
              ke(i("input", {
                "onUpdate:modelValue": f[0] || (f[0] = (C) => n.value = C),
                class: "input",
                type: "password"
              }, null, 512), [
                [ze, n.value]
              ])
            ]),
            i("div", Jd, [
              f[11] || (f[11] = i("label", null, "新密码", -1)),
              ke(i("input", {
                "onUpdate:modelValue": f[1] || (f[1] = (C) => l.value = C),
                class: "input",
                type: "password"
              }, null, 512), [
                [ze, l.value]
              ])
            ]),
            i("div", zd, [
              f[12] || (f[12] = i("label", null, "确认新密码", -1)),
              ke(i("input", {
                "onUpdate:modelValue": f[2] || (f[2] = (C) => o.value = C),
                class: "input",
                type: "password"
              }, null, 512), [
                [ze, o.value]
              ])
            ])
          ]),
          i("button", {
            class: "btn btn-primary",
            onClick: r
          }, "确认修改")
        ])
      ]);
    };
  }
}, Yd = { class: "panel" }, Xd = {
  key: 0,
  class: "kv-list"
}, Qd = { class: "panel" }, Zd = {
  key: 0,
  class: "code-block"
}, ef = {
  key: 1,
  class: "panel"
}, tf = {
  key: 1,
  class: "kv-list"
}, sf = {
  __name: "SystemView",
  setup(e, { expose: t }) {
    const s = /* @__PURE__ */ H(null), n = /* @__PURE__ */ H(null), l = /* @__PURE__ */ H(null), o = /* @__PURE__ */ H(""), a = /* @__PURE__ */ H("");
    async function r() {
      var c;
      a.value = "", o.value = "";
      try {
        const [f, h] = await Me(() => Promise.all([G.stats(), G.health()]));
        s.value = f, n.value = h;
      } catch (f) {
        a.value = String(f.message || f);
      }
      if ((c = F.user) != null && c.is_auditor)
        try {
          l.value = await G.ingestStatus();
        } catch (f) {
          o.value = String(f.message || f);
        }
    }
    return Ot(r), t({ load: r }), (c, f) => {
      var h;
      return g(), y("div", null, [
        a.value ? (g(), pe($e, {
          key: 0,
          kind: "error",
          title: "加载失败",
          desc: a.value
        }, null, 8, ["desc"])) : W("", !0),
        i("div", Yd, [
          f[4] || (f[4] = i("div", { class: "panel-head" }, [
            i("h3", null, "运行概况")
          ], -1)),
          s.value ? (g(), y("ul", Xd, [
            i("li", null, [
              f[0] || (f[0] = i("span", null, "状态", -1)),
              i("b", null, _(s.value.status), 1)
            ]),
            i("li", null, [
              f[1] || (f[1] = i("span", null, "数据库", -1)),
              i("b", null, _(s.value.mysql), 1)
            ]),
            i("li", null, [
              f[2] || (f[2] = i("span", null, "文档数", -1)),
              i("b", null, _(s.value.documents), 1)
            ]),
            i("li", null, [
              f[3] || (f[3] = i("span", null, "分块数", -1)),
              i("b", null, _(s.value.chunks), 1)
            ])
          ])) : (g(), pe($e, {
            key: 1,
            kind: "loading",
            title: "加载中…"
          }))
        ]),
        i("div", Qd, [
          f[5] || (f[5] = i("div", { class: "panel-head" }, [
            i("h3", null, "存活探测")
          ], -1)),
          n.value ? (g(), y("pre", Zd, _(JSON.stringify(n.value, null, 2)), 1)) : (g(), pe($e, {
            key: 1,
            kind: "loading",
            title: "加载中…"
          }))
        ]),
        (h = ie(F).user) != null && h.is_auditor ? (g(), y("div", ef, [
          f[10] || (f[10] = i("div", { class: "panel-head" }, [
            i("h3", null, "入库流程状态")
          ], -1)),
          o.value ? (g(), pe($e, {
            key: 0,
            kind: "error",
            title: "不可读",
            desc: o.value
          }, null, 8, ["desc"])) : l.value ? (g(), y("ul", tf, [
            i("li", null, [
              f[6] || (f[6] = i("span", null, "文档总数", -1)),
              i("b", null, _(l.value.documents_total), 1)
            ]),
            i("li", null, [
              f[7] || (f[7] = i("span", null, "分块总数", -1)),
              i("b", null, _(l.value.chunks_total), 1)
            ]),
            i("li", null, [
              f[8] || (f[8] = i("span", null, "FAISS 向量", -1)),
              i("b", null, _(l.value.faiss_total ?? "—"), 1)
            ]),
            i("li", null, [
              f[9] || (f[9] = i("span", null, "索引一致性", -1)),
              i("b", {
                style: es({ color: l.value.faiss_mysql_consistent ? "var(--c-ok)" : "var(--c-err)" })
              }, _(l.value.faiss_mysql_consistent ? "一致" : "不一致（脏数据）"), 5)
            ])
          ])) : (g(), pe($e, {
            key: 2,
            kind: "loading",
            title: "加载中…"
          }))
        ])) : W("", !0)
      ]);
    };
  }
}, nf = { class: "tabs" }, lf = ["onClick"], of = {
  key: 0,
  class: "form-hint",
  style: { margin: "0 0 8px" }
}, rf = {
  key: 1,
  class: "empty"
}, af = {
  key: 2,
  class: "table"
}, uf = { key: 0 }, cf = {
  colspan: "7",
  class: "empty"
}, df = { style: { "font-weight": "500" } }, ff = ["title"], pf = ["onClick"], hf = ["onClick"], vf = ["onClick"], mf = ["onClick"], gf = ["disabled", "onClick"], _f = ["disabled", "onClick"], yf = ["onClick"], bf = {
  key: 3,
  class: "modal active"
}, kf = {
  class: "modal-dialog",
  style: { "max-width": "820px" }
}, $f = { class: "modal-head" }, wf = { class: "modal-body" }, xf = {
  key: 0,
  class: "empty"
}, Sf = {
  key: 0,
  class: "ticket-blind-hint"
}, Cf = {
  class: "info-list",
  style: { "margin-bottom": "18px" }
}, Tf = { class: "info-item" }, Af = { class: "info-val" }, Of = { class: "info-item" }, Ef = { class: "info-val" }, Pf = { class: "info-item" }, If = { class: "info-val" }, Rf = { class: "info-item" }, Nf = { class: "info-val" }, Mf = { class: "info-item" }, jf = { class: "info-val" }, Df = { class: "info-item" }, Ff = { class: "info-val" }, Uf = {
  key: 0,
  class: "info-item"
}, Lf = { class: "info-val" }, Vf = {
  key: 1,
  class: "info-item"
}, Hf = { class: "info-val" }, Kf = { style: { "margin-bottom": "8px", "font-size": "14px" } }, Bf = {
  key: 0,
  class: "form-hint",
  style: { "margin-bottom": "6px" }
}, qf = {
  class: "table-wrap",
  style: { "margin-bottom": "18px" }
}, Wf = { class: "table" }, Jf = ["title"], zf = { style: { "max-width": "110px", overflow: "hidden", "text-overflow": "ellipsis", "white-space": "nowrap" } }, Gf = ["title"], Yf = ["onClick"], Xf = {
  key: 1,
  class: "form-hint",
  title: "安全职级不足以读取该文档正文"
}, Qf = {
  key: 2,
  class: "form-hint"
}, Zf = { key: 0 }, ep = {
  colspan: "6",
  style: { background: "var(--panel-bg)", padding: "6px 10px" }
}, tp = {
  class: "form-hint",
  style: { margin: "0", "max-height": "60px", overflow: "hidden" }
}, sp = {
  key: 0,
  class: "ticket-summary",
  style: { "margin-bottom": "12px" }
}, np = {
  key: 1,
  style: { "margin-bottom": "14px" }
}, lp = { class: "ticket-payload" }, ip = {
  key: 2,
  class: "form-hint"
}, op = {
  key: 3,
  class: "form-hint",
  style: { color: "var(--c-err)", "font-weight": "500", margin: "8px 0" }
}, rp = {
  key: 3,
  class: "ticket-files"
}, ap = ["onClick"], up = {
  class: "info-list",
  style: { "margin-top": "12px" }
}, cp = {
  key: 0,
  class: "info-item"
}, dp = {
  class: "info-val",
  style: { "font-family": "var(--mono)", "font-size": "11.5px", "word-break": "break-all" }
}, fp = {
  key: 1,
  class: "info-item"
}, pp = {
  class: "info-val",
  style: { "font-family": "var(--mono)", "font-size": "11.5px", "word-break": "break-all" }
}, hp = {
  key: 2,
  class: "info-item"
}, vp = { class: "info-val" }, mp = {
  key: 3,
  class: "info-item"
}, gp = { class: "info-val" }, _p = {
  key: 4,
  class: "info-item"
}, yp = { class: "info-val" }, bp = {
  key: 4,
  class: "ticket-checklist"
}, kp = {
  key: 0,
  class: "form-item",
  style: { "margin-top": "14px" }
}, $p = {
  key: 1,
  class: "form-item"
}, wp = { class: "modal-actions" }, xp = ["disabled"], Sp = ["disabled"], Cp = ["disabled"], Tp = {
  key: 2,
  class: "form-hint"
}, Ap = {
  key: 4,
  class: "modal active"
}, Op = {
  class: "modal-dialog",
  style: { "max-width": "560px" }
}, Ep = { class: "modal-head" }, Pp = { class: "modal-body" }, Ip = { class: "info-list" }, Rp = { class: "info-item" }, Np = { class: "info-val" }, Mp = { class: "info-item" }, jp = { class: "info-val" }, Dp = { class: "info-item" }, Fp = { class: "info-val" }, Up = { class: "info-item" }, Lp = { class: "info-val" }, Vp = { class: "info-item" }, Hp = { class: "info-val" }, Kp = { class: "info-item" }, Bp = { class: "info-val" }, qp = { class: "info-item" }, Wp = { class: "info-val" }, Jp = { class: "info-item" }, zp = { class: "info-val" }, Gp = { class: "info-item" }, Yp = { class: "info-val" }, Xp = { style: { display: "flex", gap: "8px" } }, Qp = {
  key: 0,
  class: "modal-actions"
}, Zp = ["disabled"], eh = ["disabled"], th = {
  key: 1,
  class: "form-hint"
}, sh = {
  __name: "TicketsView",
  setup(e, { expose: t }) {
    const s = [
      { key: "mine", label: "我的申请", load: D },
      // 待我审批 = 两体系合并：tickets 工单 + governance 发布申请（用户不感知体系差异）
      { key: "approval", label: "待我审批", load: se },
      // 已完成 = tickets 终态工单 + governance 已决策发布申请，统一为办结历史
      { key: "done", label: "已完成", load: U }
    ], n = /* @__PURE__ */ H("mine"), l = /* @__PURE__ */ H([]), o = /* @__PURE__ */ H(!1), a = /* @__PURE__ */ H(!1), r = /* @__PURE__ */ H(null), c = /* @__PURE__ */ H(null), f = {
      doc_batch_delete: "删除文档",
      doc_restore: "恢复文档",
      doc_upload: "上传文档",
      doc_update: "更新文档"
    }, h = {
      upload: "上传入库",
      update_version: "更新版本",
      update_policy: "变更属性",
      rollback: "版本回滚"
    };
    function k(w) {
      var b, z, u, m;
      return {
        kind: "ticket",
        raw: w,
        id: w.id,
        no: w.ticket_no || `#${w.id}`,
        type: f[w.module] || w.module_label || w.module,
        applicant: ((b = w.applicant) == null ? void 0 : b.name) || ((z = w.applicant) == null ? void 0 : z.employee_no) || "—",
        approver: ((u = w.approver) == null ? void 0 : u.name) || ((m = w.approver) == null ? void 0 : m.employee_no) || "—",
        status: w.status,
        label: w.status_label || L[w.status] || w.status,
        closed_at: w.executed_at || w.created_at
      };
    }
    function R(w) {
      const b = Oe(w), z = String(b.reason || ""), u = w.action || b.action || (z.includes("回滚") ? "rollback" : z.includes("上传入库") ? "upload" : "");
      return {
        kind: "gov",
        raw: w,
        id: w.id,
        no: w.title || w.filename || `#${w.document_id}`,
        type: h[u] || "发布审批",
        action: u,
        reason: z,
        applicant: w.requester_name || w.requester_no || "—",
        approver: w.approver_name || w.approver_no || "—",
        status: w.status,
        label: X[w.status] || w.status,
        closed_at: w.created_at
      };
    }
    function O(w, b) {
      let z = w;
      if (typeof z == "string")
        try {
          z = JSON.parse(z);
        } catch {
          z = [];
        }
      return Array.isArray(z) && z.length ? z.join(", ") : b && b !== "*" ? b : b === "*" ? "不限部门" : "—";
    }
    function C(w) {
      return w ? O(w.departments, w.owner_department) : "—";
    }
    async function j(w) {
      return { items: ((w == null ? void 0 : w.items) ?? []).map(k) };
    }
    async function D() {
      const [w, b] = await Promise.all([
        G.ticketsMine().catch(() => ({ items: [] })),
        G.governanceRequests().catch(() => ({ items: [] }))
      ]), z = ((w == null ? void 0 : w.items) ?? []).map(k), u = ((b == null ? void 0 : b.items) ?? []).filter((E) => {
        var x;
        return Number(E.requested_by) === Number((x = F.user) == null ? void 0 : x.id);
      }).map(R), m = (E) => E.status === "pending" ? 0 : 1;
      return { items: [...z, ...u].sort((E, x) => m(E) - m(x) || String(x.closed_at || "").localeCompare(String(E.closed_at || ""))) };
    }
    async function se() {
      const [w, b] = await Promise.all([
        G.ticketsPendingApproval().catch(() => ({ items: [] })),
        G.governanceRequests("pending").catch(() => ({ items: [] }))
      ]), z = ((w == null ? void 0 : w.items) ?? []).map(k), u = ((b == null ? void 0 : b.items) ?? []).filter((m) => {
        var $;
        return m.status === "pending" && Number(m.approver_id) === Number(($ = F.user) == null ? void 0 : $.id);
      }).map(R);
      return { items: [...z, ...u] };
    }
    async function U() {
      const [w, b] = await Promise.all([
        G.ticketsDone().catch(() => ({ items: [] })),
        G.governanceRequests("approved,rejected").catch(() => ({ items: [] }))
      ]), z = ((b == null ? void 0 : b.items) ?? []).map(R);
      return { items: [...(await j(w)).items, ...z] };
    }
    const L = {
      pending: "待审批",
      approved: "已批准",
      rejected: "已驳回",
      executed: "已执行",
      cancelled: "已撤销",
      timeout: "已超时",
      tampered: "已篡改"
    }, I = {
      pending: "badge--warn",
      approved: "badge--info",
      executed: "badge--ok",
      rejected: "badge--err",
      timeout: "badge--err",
      tampered: "badge--err",
      cancelled: "badge--neutral"
    }, X = { pending: "待审批", approved: "已通过", rejected: "已驳回" }, ve = { pending: "badge--warn", approved: "badge--ok", rejected: "badge--err" };
    function _e(w) {
      return w.status === "pending" ? xe(w.raw) ? { text: "待我审批", cls: "badge--warn" } : { text: "进行中", cls: "badge--info" } : { text: "已完成", cls: ["rejected", "timeout", "tampered"].includes(w.status) ? "badge--err" : "badge--ok" };
    }
    const ye = Ce(() => {
      const w = { running: 0, mine: 0, done: 0 };
      for (const b of l.value) {
        const { text: z } = _e(b);
        z === "待我审批" ? w.mine += 1 : z === "进行中" ? w.running += 1 : w.done += 1;
      }
      return w;
    }), ot = Ce(() => n.value === "done" ? "暂无已办结记录" : n.value === "approval" ? "暂无待我审批的单据" : "暂无申请记录");
    async function we() {
      var w, b;
      o.value = !0;
      try {
        const z = (w = s.find((u) => u.key === n.value)) == null ? void 0 : w.load;
        z && (l.value = ((b = await z()) == null ? void 0 : b.items) ?? []);
      } catch (z) {
        l.value = [], ee("加载失败：" + ((z == null ? void 0 : z.message) || z), "error");
      } finally {
        o.value = !1;
      }
    }
    function Oe(w) {
      try {
        return typeof w.policy == "string" ? JSON.parse(w.policy) : w.policy || {};
      } catch {
        return {};
      }
    }
    const Z = /* @__PURE__ */ H(null);
    function q(w) {
      Z.value = w;
    }
    async function Y() {
      try {
        await G.download(
          Number(Z.value.document_id),
          Z.value.title || Z.value.filename || ""
        );
      } catch (w) {
        ee("下载失败：" + ((w == null ? void 0 : w.message) || w), "error");
      }
    }
    function xe(w) {
      var b;
      return n.value === "approval" && w.status === "pending" && Number(w.approver_id) === Number((b = F.user) == null ? void 0 : b.id);
    }
    async function J(w, b) {
      if (!a.value) {
        a.value = !0;
        try {
          await G.decideRequest(w.id, b), ee(b ? "已通过" : "已驳回", b ? "ok" : "info"), Z.value = null, await we();
        } catch (z) {
          ee((b ? "通过" : "驳回") + "失败：" + ((z == null ? void 0 : z.message) || z), "error");
        } finally {
          a.value = !1;
        }
      }
    }
    async function le(w, b = !1) {
      r.value = {
        ticket: w.raw || w,
        view: b,
        loading: !0,
        comment: "",
        reason: ""
      }, await He(w.id);
    }
    async function re(w) {
      r.value = { ticket: { id: w }, view: !1, loading: !0, comment: "", reason: "" }, await He(w);
    }
    async function He(w) {
      try {
        const b = await Me(() => G.ticket(w));
        r.value && (r.value.ticket = b);
      } catch (b) {
        ee("工单详情加载失败：" + ((b == null ? void 0 : b.message) || b), "error"), r.value = null;
      } finally {
        r.value && (r.value.loading = !1);
      }
    }
    const rt = Ce(
      () => {
        var w, b, z, u;
        return ((b = (w = r.value) == null ? void 0 : w.ticket) == null ? void 0 : b.payload) == null && !!((u = (z = r.value) == null ? void 0 : z.ticket) != null && u.qualification_checklist);
      }
    ), Qe = Ce(() => {
      var w, b;
      return ((b = (w = r.value) == null ? void 0 : w.ticket) == null ? void 0 : b.module) === "doc_batch_delete";
    }), Ee = Ce(() => {
      var w, b;
      return ((b = (w = r.value) == null ? void 0 : w.ticket) == null ? void 0 : b.doc_references) || [];
    }), zt = Ce(() => Ee.value.some((w) => w.snapshot === !1));
    function N(w) {
      return w ? `${w.name || w.username || ""}（${w.no || w.employee_no || ""}）` : "—";
    }
    const Je = (w) => (w || "").replace("T", " ").slice(0, 19);
    async function Ze(w) {
      var z;
      const b = (z = r.value) == null ? void 0 : z.ticket;
      if (!(!b || a.value)) {
        if (w === "reject" && (r.value.reason || "").trim().length < 2) {
          ee("请填写驳回原因（至少 2 个字）", "error");
          return;
        }
        a.value = !0;
        try {
          w === "approve" ? await G.approveTicket(b.id, r.value.comment.trim()) : w === "reject" ? await G.rejectTicket(b.id, r.value.reason.trim()) : w === "cancel" && await G.cancelTicket(b.id), ee(w === "approve" ? "已审批通过" : w === "reject" ? "已驳回" : "已撤回", "ok"), r.value = null, await we();
        } catch (u) {
          ee("操作失败：" + ((u == null ? void 0 : u.message) || u), "error");
        } finally {
          a.value = !1;
        }
      }
    }
    async function Et(w, b) {
      try {
        await G.ticketFile(w, b);
      } catch (z) {
        ee("下载失败：" + ((z == null ? void 0 : z.message) || z), "error");
      }
    }
    return st(
      () => F.jumpTicketId,
      (w) => {
        w != null && (F.jumpTicketId = null, n.value = "mine", re(w));
      }
    ), Ot(we), t({ load: we }), (w, b) => {
      var z;
      return g(), y("div", null, [
        b[53] || (b[53] = i("p", {
          class: "form-hint",
          style: { margin: "0 0 10px" }
        }, " 每一次文档操作都会在这里留痕：上传入库、更新版本、变更属性、版本回滚、删除文档、恢复文档。 状态只有三种——「进行中」表示已提交、审批人还在处理；「待我审批」表示该你处理了；「已完成」表示已办结（具体通过还是驳回见状态列悬停提示）。 ", -1)),
        i("nav", nf, [
          (g(), y(V, null, ne(s, (u) => i("button", {
            key: u.key,
            class: ge(["tab", { active: n.value === u.key }]),
            onClick: (m) => {
              n.value = u.key, we();
            }
          }, _(u.label), 11, lf)), 64))
        ]),
        !o.value && l.value.length ? (g(), y("p", of, " 进行中 " + _(ye.value.running) + " 条 · 待我审批 " + _(ye.value.mine) + " 条 · 已完成 " + _(ye.value.done) + " 条 ", 1)) : W("", !0),
        o.value ? (g(), y("div", rf, "加载中…")) : (g(), y("table", af, [
          i("thead", null, [
            i("tr", null, [
              b[15] || (b[15] = i("th", null, "对象", -1)),
              b[16] || (b[16] = i("th", null, "操作类型", -1)),
              b[17] || (b[17] = i("th", null, "申请人", -1)),
              b[18] || (b[18] = i("th", null, "审批人", -1)),
              b[19] || (b[19] = i("th", null, "阶段", -1)),
              i("th", null, _(n.value === "done" ? "办结时间" : "创建时间"), 1),
              b[20] || (b[20] = i("th", null, "操作", -1))
            ])
          ]),
          i("tbody", null, [
            l.value.length ? W("", !0) : (g(), y("tr", uf, [
              i("td", cf, _(ot.value), 1)
            ])),
            (g(!0), y(V, null, ne(l.value, (u) => (g(), y("tr", {
              key: u.id
            }, [
              i("td", df, _(u.no), 1),
              i("td", null, _(u.type), 1),
              i("td", null, _(u.applicant), 1),
              i("td", null, _(u.approver), 1),
              i("td", null, [
                i("span", {
                  class: ge(["badge", _e(u).cls]),
                  title: `当前状态：${u.label}`
                }, _(_e(u).text), 11, ff)
              ]),
              i("td", null, _((u.closed_at || "").replace("T", " ").slice(0, 16)), 1),
              i("td", null, [
                u.kind === "ticket" ? (g(), y(V, { key: 0 }, [
                  n.value === "approval" && u.status === "pending" ? (g(), y("button", {
                    key: 0,
                    class: "btn btn-sm btn-primary",
                    onClick: (m) => le(u.raw)
                  }, "审批", 8, pf)) : (g(), y("button", {
                    key: 1,
                    class: "btn btn-sm",
                    onClick: (m) => le(u.raw, !0)
                  }, "详情", 8, hf)),
                  n.value === "mine" && u.status === "pending" ? (g(), y("button", {
                    key: 2,
                    class: "btn btn-sm btn-danger",
                    onClick: (m) => le(u.raw)
                  }, "撤销", 8, vf)) : W("", !0)
                ], 64)) : xe(u.raw) ? (g(), y(V, { key: 1 }, [
                  i("button", {
                    class: "btn btn-sm",
                    onClick: (m) => q(u.raw)
                  }, "详情", 8, mf),
                  i("button", {
                    class: "btn btn-sm btn-primary",
                    disabled: a.value,
                    onClick: (m) => J(u.raw, !0)
                  }, "通过", 8, gf),
                  i("button", {
                    class: "btn btn-sm btn-danger",
                    disabled: a.value,
                    onClick: (m) => J(u.raw, !1)
                  }, "驳回", 8, _f)
                ], 64)) : (g(), y("button", {
                  key: 2,
                  class: "btn btn-sm",
                  onClick: (m) => q(u.raw)
                }, "详情", 8, yf))
              ])
            ]))), 128))
          ])
        ])),
        r.value ? (g(), y("div", bf, [
          i("div", {
            class: "modal-mask",
            onClick: b[0] || (b[0] = (u) => r.value = null)
          }),
          i("div", kf, [
            i("div", $f, [
              i("h3", null, "工单 " + _(r.value.ticket.ticket_no || `#${r.value.ticket.id}`), 1),
              i("button", {
                class: "modal-close",
                onClick: b[1] || (b[1] = (u) => r.value = null)
              }, "✕")
            ]),
            i("div", wf, [
              r.value.loading ? (g(), y("div", xf, "加载中…")) : (g(), y(V, { key: 1 }, [
                rt.value ? (g(), y("div", Sf, [...b[21] || (b[21] = [
                  i("span", null, "🔒 盲执行视图：申请内容已隐藏，请按核验清单逐项确认后执行。", -1)
                ])])) : W("", !0),
                i("div", Cf, [
                  i("div", Tf, [
                    b[22] || (b[22] = i("span", { class: "info-key" }, "工单号", -1)),
                    i("span", Af, _(r.value.ticket.ticket_no || `#${r.value.ticket.id}`), 1)
                  ]),
                  i("div", Of, [
                    b[23] || (b[23] = i("span", { class: "info-key" }, "模块", -1)),
                    i("span", Ef, _(r.value.ticket.module_label || r.value.ticket.module), 1)
                  ]),
                  i("div", Pf, [
                    b[24] || (b[24] = i("span", { class: "info-key" }, "状态", -1)),
                    i("span", If, [
                      i("span", {
                        class: ge(["badge", I[r.value.ticket.status] || "badge--neutral"])
                      }, _(r.value.ticket.status_label || L[r.value.ticket.status] || r.value.ticket.status), 3)
                    ])
                  ]),
                  i("div", Rf, [
                    b[25] || (b[25] = i("span", { class: "info-key" }, "申请人", -1)),
                    i("span", Nf, _(N(r.value.ticket.applicant)), 1)
                  ]),
                  i("div", Mf, [
                    b[26] || (b[26] = i("span", { class: "info-key" }, "审批人", -1)),
                    i("span", jf, _(N(r.value.ticket.approver)), 1)
                  ]),
                  i("div", Df, [
                    b[27] || (b[27] = i("span", { class: "info-key" }, "创建时间", -1)),
                    i("span", Ff, _(Je(r.value.ticket.created_at)), 1)
                  ]),
                  r.value.ticket.approved_at ? (g(), y("div", Uf, [
                    b[28] || (b[28] = i("span", { class: "info-key" }, "审批时间", -1)),
                    i("span", Lf, _(Je(r.value.ticket.approved_at)), 1)
                  ])) : W("", !0),
                  r.value.ticket.executed_at ? (g(), y("div", Vf, [
                    b[29] || (b[29] = i("span", { class: "info-key" }, "执行时间", -1)),
                    i("span", Hf, _(Je(r.value.ticket.executed_at)), 1)
                  ])) : W("", !0)
                ]),
                Ee.value.length ? (g(), y(V, { key: 1 }, [
                  i("h4", Kf, "关联文档（" + _(Ee.value.length) + " 篇）", 1),
                  zt.value ? (g(), y("p", Bf, " 该工单建于快照机制上线前，以下为实时查询结果（非冻结快照） ")) : W("", !0),
                  i("div", qf, [
                    i("table", Wf, [
                      b[31] || (b[31] = i("thead", null, [
                        i("tr", null, [
                          i("th", { style: { width: "48px" } }, "ID"),
                          i("th", null, "文件名"),
                          i("th", { style: { width: "64px" } }, "密级"),
                          i("th", { style: { width: "110px" } }, "归属部门"),
                          i("th", { style: { width: "70px" } }, "状态"),
                          i("th", { style: { width: "110px" } }, "操作")
                        ])
                      ], -1)),
                      i("tbody", null, [
                        (g(!0), y(V, null, ne(Ee.value, (u) => (g(), y(V, {
                          key: u.id
                        }, [
                          i("tr", null, [
                            i("td", null, _(u.id), 1),
                            i("td", {
                              style: { "max-width": "220px", overflow: "hidden", "text-overflow": "ellipsis", "white-space": "nowrap" },
                              title: u.title || u.filename
                            }, _(u.filename || `文档 #${u.id}`), 9, Jf),
                            i("td", null, _(ie(Be).levelName(u.classification ?? 0)), 1),
                            i("td", zf, _(O(u.departments, u.owner_department)), 1),
                            i("td", null, [
                              i("span", {
                                class: ge(["status-pill", u.exists === !1 ? "txt" : u.recycled ? "warn" : "ok"]),
                                title: u.exists === !1 ? "文档已被物理销毁" : u.recycled ? "已移入回收站，宽限期内可发起恢复工单找回" : "文档仍存在"
                              }, [
                                b[30] || (b[30] = i("span", { class: "dot" }, null, -1)),
                                nt(_(u.exists === !1 ? "已销毁" : u.recycled ? "回收站" : "在库"), 1)
                              ], 10, Gf)
                            ]),
                            i("td", null, [
                              u.exists !== !1 && u.can_view ? (g(), y("button", {
                                key: 0,
                                class: "btn btn-sm",
                                onClick: (m) => c.value = { id: u.id, classification: u.classification ?? 0 }
                              }, "📄 查看内容", 8, Yf)) : u.exists !== !1 ? (g(), y("span", Xf, "🔒 不可读")) : (g(), y("span", Qf, "已物理销毁"))
                            ])
                          ]),
                          u.snippet ? (g(), y("tr", Zf, [
                            i("td", ep, [
                              i("div", tp, _(u.snippet), 1)
                            ])
                          ])) : W("", !0)
                        ], 64))), 128))
                      ])
                    ])
                  ])
                ], 64)) : W("", !0),
                rt.value ? W("", !0) : (g(), y(V, { key: 2 }, [
                  b[34] || (b[34] = i("h4", { style: { "margin-bottom": "8px", "font-size": "14px" } }, "申请内容", -1)),
                  r.value.ticket.payload_summary ? (g(), y("div", sp, [
                    b[32] || (b[32] = i("strong", null, "摘要：", -1)),
                    nt(_(r.value.ticket.payload_summary), 1)
                  ])) : W("", !0),
                  r.value.ticket.payload ? (g(), y("details", np, [
                    b[33] || (b[33] = i("summary", { class: "form-hint" }, "原始 payload（审计留痕，可折叠）", -1)),
                    i("pre", lp, _(JSON.stringify(r.value.ticket.payload, null, 2)), 1)
                  ])) : W("", !0),
                  !r.value.ticket.payload_summary && !r.value.ticket.payload ? (g(), y("p", ip, "（无申请内容）")) : W("", !0),
                  Qe.value ? (g(), y("div", op, " ⚠️ 审批通过后系统将立即永久删除以上文档及其分块、密级记录与向量索引，此操作不可撤销。 ")) : W("", !0)
                ], 64)),
                (z = r.value.ticket.files) != null && z.length ? (g(), y("div", rp, [
                  b[35] || (b[35] = i("strong", null, "待审文件：", -1)),
                  (g(!0), y(V, null, ne(r.value.ticket.files, (u, m) => (g(), y("button", {
                    key: m,
                    class: "btn btn-sm",
                    onClick: ($) => Et(r.value.ticket.id, m)
                  }, "📎 " + _(u.name || `文件${m + 1}`), 9, ap))), 128))
                ])) : W("", !0),
                i("div", up, [
                  r.value.ticket.original_hash ? (g(), y("div", cp, [
                    b[36] || (b[36] = i("span", { class: "info-key" }, "原始哈希", -1)),
                    i("span", dp, _(r.value.ticket.original_hash), 1)
                  ])) : W("", !0),
                  r.value.ticket.approved_hash ? (g(), y("div", fp, [
                    b[37] || (b[37] = i("span", { class: "info-key" }, "审批哈希", -1)),
                    i("span", pp, _(r.value.ticket.approved_hash), 1)
                  ])) : W("", !0),
                  r.value.ticket.approve_comment ? (g(), y("div", hp, [
                    b[38] || (b[38] = i("span", { class: "info-key" }, "审批意见", -1)),
                    i("span", vp, _(r.value.ticket.approve_comment), 1)
                  ])) : W("", !0),
                  r.value.ticket.exec_result ? (g(), y("div", mp, [
                    b[39] || (b[39] = i("span", { class: "info-key" }, "执行结果", -1)),
                    i("span", gp, _(r.value.ticket.exec_result), 1)
                  ])) : W("", !0),
                  r.value.ticket.reason ? (g(), y("div", _p, [
                    b[40] || (b[40] = i("span", { class: "info-key" }, "驳回/退回原因", -1)),
                    i("span", yp, _(r.value.ticket.reason), 1)
                  ])) : W("", !0)
                ]),
                r.value.ticket.qualification_checklist ? (g(), y("div", bp, [
                  b[41] || (b[41] = i("h4", { style: { "margin-bottom": "8px", "font-size": "14px" } }, "执行核验清单", -1)),
                  i("ul", null, [
                    (g(!0), y(V, null, ne(r.value.ticket.qualification_checklist, (u, m) => (g(), y("li", { key: m }, _(typeof u == "string" ? u : u.label || JSON.stringify(u)), 1))), 128))
                  ])
                ])) : W("", !0),
                r.value.view ? W("", !0) : (g(), y(V, { key: 5 }, [
                  r.value.ticket.can_approve ? (g(), y("div", kp, [
                    b[42] || (b[42] = i("label", null, "审批意见（通过时选填）", -1)),
                    ke(i("textarea", {
                      "onUpdate:modelValue": b[2] || (b[2] = (u) => r.value.comment = u),
                      class: "input",
                      rows: "2",
                      placeholder: "审批意见（可选）"
                    }, null, 512), [
                      [ze, r.value.comment]
                    ])
                  ])) : W("", !0),
                  r.value.ticket.can_approve ? (g(), y("div", $p, [
                    b[43] || (b[43] = i("label", null, "驳回原因（驳回时必填）", -1)),
                    ke(i("textarea", {
                      "onUpdate:modelValue": b[3] || (b[3] = (u) => r.value.reason = u),
                      class: "input",
                      rows: "2",
                      placeholder: "请说明驳回原因（将通知申请人）"
                    }, null, 512), [
                      [ze, r.value.reason]
                    ])
                  ])) : W("", !0),
                  i("div", wp, [
                    r.value.ticket.can_approve ? (g(), y(V, { key: 0 }, [
                      i("button", {
                        class: "btn btn-primary",
                        disabled: a.value,
                        onClick: b[4] || (b[4] = (u) => Ze("approve"))
                      }, "✅ 审批通过", 8, xp),
                      i("button", {
                        class: "btn btn-danger",
                        disabled: a.value,
                        onClick: b[5] || (b[5] = (u) => Ze("reject"))
                      }, "驳回", 8, Sp)
                    ], 64)) : W("", !0),
                    r.value.ticket.can_cancel ? (g(), y("button", {
                      key: 1,
                      class: "btn btn-danger",
                      disabled: a.value,
                      onClick: b[6] || (b[6] = (u) => Ze("cancel"))
                    }, "撤回工单", 8, Cp)) : W("", !0)
                  ]),
                  !r.value.ticket.can_approve && !r.value.ticket.can_cancel ? (g(), y("p", Tp, " 当前身份无待办操作，仅可查看。 ")) : W("", !0)
                ], 64))
              ], 64)),
              i("button", {
                class: "btn btn-block",
                style: { "margin-top": "12px" },
                onClick: b[7] || (b[7] = (u) => r.value = null)
              }, "关闭")
            ])
          ])
        ])) : W("", !0),
        Z.value ? (g(), y("div", Ap, [
          i("div", {
            class: "modal-mask",
            onClick: b[8] || (b[8] = (u) => Z.value = null)
          }),
          i("div", Op, [
            i("div", Ep, [
              i("h3", null, _(h[Z.value.action || Oe(Z.value).action] || "发布审批") + " · 详情", 1),
              i("button", {
                class: "modal-close",
                onClick: b[9] || (b[9] = (u) => Z.value = null)
              }, "✕")
            ]),
            i("div", Pp, [
              i("div", Ip, [
                i("div", Rp, [
                  b[44] || (b[44] = i("span", { class: "info-key" }, "文档", -1)),
                  i("span", Np, _(Z.value.title || Z.value.filename || `#${Z.value.document_id}`), 1)
                ]),
                i("div", Mp, [
                  b[45] || (b[45] = i("span", { class: "info-key" }, "操作类型", -1)),
                  i("span", jp, _(h[Z.value.action || Oe(Z.value).action] || "发布审批"), 1)
                ]),
                i("div", Dp, [
                  b[46] || (b[46] = i("span", { class: "info-key" }, "目标密级", -1)),
                  i("span", Fp, _(ie(Be).levelName(Oe(Z.value).classification)), 1)
                ]),
                i("div", Up, [
                  b[47] || (b[47] = i("span", { class: "info-key" }, "归属部门", -1)),
                  i("span", Lp, _(C(Oe(Z.value))), 1)
                ]),
                i("div", Vp, [
                  b[48] || (b[48] = i("span", { class: "info-key" }, "操作说明", -1)),
                  i("span", Hp, _(Oe(Z.value).reason || "—"), 1)
                ]),
                i("div", Kp, [
                  b[49] || (b[49] = i("span", { class: "info-key" }, "申请人", -1)),
                  i("span", Bp, _(Z.value.requester_name ? `${Z.value.requester_name}（${Z.value.requester_no}）` : "—"), 1)
                ]),
                i("div", qp, [
                  b[50] || (b[50] = i("span", { class: "info-key" }, "审批人", -1)),
                  i("span", Wp, _(Z.value.approver_name ? `${Z.value.approver_name}（${Z.value.approver_no}）` : "未指派"), 1)
                ]),
                i("div", Jp, [
                  b[51] || (b[51] = i("span", { class: "info-key" }, "状态", -1)),
                  i("span", zp, [
                    i("span", {
                      class: ge(["badge", ve[Z.value.status] || "badge--neutral"])
                    }, _(X[Z.value.status] || Z.value.status), 3)
                  ])
                ]),
                i("div", Gp, [
                  b[52] || (b[52] = i("span", { class: "info-key" }, "申请时间", -1)),
                  i("span", Yp, _(Je(Z.value.created_at)), 1)
                ])
              ]),
              i("div", Xp, [
                i("button", {
                  class: "btn",
                  style: { flex: "1" },
                  onClick: b[10] || (b[10] = (u) => c.value = {
                    id: Number(Z.value.document_id),
                    classification: Oe(Z.value).classification ?? 0
                  })
                }, "📄 查看文档内容"),
                i("button", {
                  class: "btn",
                  style: { flex: "1" },
                  onClick: Y
                }, "⬇ 下载原文")
              ]),
              xe(Z.value) ? (g(), y("div", Qp, [
                i("button", {
                  class: "btn btn-primary",
                  disabled: a.value,
                  onClick: b[11] || (b[11] = (u) => J(Z.value, !0))
                }, "✅ 通过", 8, Zp),
                i("button", {
                  class: "btn btn-danger",
                  disabled: a.value,
                  onClick: b[12] || (b[12] = (u) => J(Z.value, !1))
                }, "驳回", 8, eh)
              ])) : Z.value.status === "pending" ? (g(), y("p", th, "该申请审批中，请等待审批人处理。")) : W("", !0),
              i("button", {
                class: "btn btn-block",
                style: { "margin-top": "12px" },
                onClick: b[13] || (b[13] = (u) => Z.value = null)
              }, "关闭")
            ])
          ])
        ])) : W("", !0),
        c.value ? (g(), pe(Qi, {
          key: 5,
          "doc-id": c.value.id,
          classification: c.value.classification,
          onClose: b[14] || (b[14] = (u) => c.value = null)
        }, null, 8, ["doc-id", "classification"])) : W("", !0)
      ]);
    };
  }
}, nh = { class: "panel" }, lh = { class: "kv-list" }, ih = { key: 0 }, oh = { class: "panel" }, rh = { class: "panel-head" }, ah = {
  key: 1,
  class: "table"
}, uh = {
  key: 1,
  class: "panel"
}, ch = { class: "panel-head" }, dh = { class: "panel-actions" }, fh = ["value"], ph = ["value"], hh = {
  key: 2,
  class: "table"
}, vh = { class: "type-tag txt" }, mh = ["title"], gh = ["title"], _h = {
  __name: "AdminView",
  setup(e, { expose: t }) {
    const s = /* @__PURE__ */ H([]), n = /* @__PURE__ */ H([]), l = /* @__PURE__ */ H([]), o = /* @__PURE__ */ H([]), a = /* @__PURE__ */ H(""), r = /* @__PURE__ */ H(""), c = /* @__PURE__ */ H(""), f = /* @__PURE__ */ H("");
    async function h() {
      var O;
      a.value = "", r.value = "";
      try {
        const [C, j] = await Me(() => Promise.all([G.users(), G.levels()]));
        s.value = Array.isArray(C) ? C : C.items || [], n.value = Array.isArray(j) ? j : j.items || [];
      } catch (C) {
        a.value = String(C.message || C);
      }
      if ((O = F.user) != null && O.is_auditor)
        try {
          const [C] = await Me(
            () => Promise.all([G.auditActions(), k()])
          );
          o.value = Array.isArray(C) ? C : C.items || [];
        } catch (C) {
          r.value = String(C.message || C);
        }
    }
    async function k() {
      const O = { limit: 200 };
      c.value && (O.action = c.value), f.value && (O.employee_no = f.value);
      const C = await G.auditLogs(O);
      return l.value = Array.isArray(C) ? C : C.items || [], C;
    }
    async function R() {
      var O;
      if ((O = F.user) != null && O.is_auditor) {
        r.value = "";
        try {
          await Me(k);
        } catch (C) {
          r.value = String(C.message || C);
        }
      }
    }
    return Ot(h), t({ load: h }), (O, C) => {
      var j;
      return g(), y("div", null, [
        a.value ? (g(), pe($e, {
          key: 0,
          kind: "error",
          title: "加载失败",
          desc: a.value
        }, null, 8, ["desc"])) : W("", !0),
        i("div", nh, [
          C[3] || (C[3] = i("div", { class: "panel-head" }, [
            i("h3", null, "安全职级")
          ], -1)),
          i("ul", lh, [
            (g(!0), y(V, null, ne(n.value, (D) => (g(), y("li", {
              key: D.level
            }, [
              i("span", null, "L" + _(D.level), 1),
              i("b", null, _(D.name), 1)
            ]))), 128)),
            n.value.length ? W("", !0) : (g(), y("li", ih, [...C[2] || (C[2] = [
              i("span", null, "暂无", -1)
            ])]))
          ])
        ]),
        i("div", oh, [
          i("div", rh, [
            i("h3", null, "员工（" + _(s.value.length) + "）", 1)
          ]),
          !s.value.length && !a.value ? (g(), pe($e, {
            key: 0,
            kind: "empty",
            title: "暂无数据"
          })) : (g(), y("table", ah, [
            C[4] || (C[4] = i("thead", null, [
              i("tr", null, [
                i("th", null, "工号"),
                i("th", null, "姓名"),
                i("th", null, "部门"),
                i("th", null, "职级"),
                i("th", null, "在职")
              ])
            ], -1)),
            i("tbody", null, [
              (g(!0), y(V, null, ne(s.value, (D) => (g(), y("tr", {
                key: D.employee_no || D.id
              }, [
                i("td", null, _(D.employee_no), 1),
                i("td", null, _(D.username), 1),
                i("td", null, _(D.department), 1),
                i("td", null, "L" + _(D.security_level ?? D.level), 1),
                i("td", null, _(D.is_active ? "是" : "否"), 1)
              ]))), 128))
            ])
          ])),
          C[5] || (C[5] = i("p", { class: "form-hint" }, "人事主数据由 HR 系统维护，KMS 不可修改。", -1))
        ]),
        (j = ie(F).user) != null && j.is_auditor ? (g(), y("div", uh, [
          i("div", ch, [
            C[8] || (C[8] = i("h3", null, "审计日志", -1)),
            i("div", dh, [
              ke(i("select", {
                "onUpdate:modelValue": C[0] || (C[0] = (D) => c.value = D),
                class: "input",
                onChange: R
              }, [
                C[6] || (C[6] = i("option", { value: "" }, "全部操作类型", -1)),
                (g(!0), y(V, null, ne(o.value, (D) => (g(), y("option", {
                  key: D.action,
                  value: D.action
                }, _(D.action) + "（" + _(D.count) + "） ", 9, fh))), 128))
              ], 544), [
                [wt, c.value]
              ]),
              ke(i("select", {
                "onUpdate:modelValue": C[1] || (C[1] = (D) => f.value = D),
                class: "input",
                onChange: R
              }, [
                C[7] || (C[7] = i("option", { value: "" }, "全部工号", -1)),
                (g(!0), y(V, null, ne(s.value, (D) => (g(), y("option", {
                  key: D.employee_no || D.id,
                  value: D.employee_no
                }, _(D.employee_no) + " " + _(D.username || ""), 9, ph))), 128))
              ], 544), [
                [wt, f.value]
              ]),
              i("button", {
                class: "btn",
                onClick: R
              }, "刷新")
            ])
          ]),
          r.value ? (g(), pe($e, {
            key: 0,
            kind: "error",
            title: "不可读",
            desc: r.value
          }, null, 8, ["desc"])) : l.value.length ? (g(), y("table", hh, [
            C[9] || (C[9] = i("thead", null, [
              i("tr", null, [
                i("th", null, "时间"),
                i("th", null, "工号"),
                i("th", null, "操作"),
                i("th", null, "对象"),
                i("th", null, "详情"),
                i("th", null, "IP")
              ])
            ], -1)),
            i("tbody", null, [
              (g(!0), y(V, null, ne(l.value, (D, se) => (g(), y("tr", { key: se }, [
                i("td", null, _((D.created_at || "").replace("T", " ").slice(0, 19)), 1),
                i("td", null, _(D.employee_no || "—"), 1),
                i("td", null, [
                  i("span", vh, _(D.action), 1)
                ]),
                i("td", {
                  style: { "max-width": "200px", overflow: "hidden", "text-overflow": "ellipsis", "white-space": "nowrap" },
                  title: D.target
                }, _(D.target || "—"), 9, mh),
                i("td", {
                  style: { "max-width": "280px", overflow: "hidden", "text-overflow": "ellipsis", "white-space": "nowrap" },
                  title: D.detail
                }, _(D.detail || "—"), 9, gh),
                i("td", null, _(D.ip || "—"), 1)
              ]))), 128))
            ])
          ])) : (g(), pe($e, {
            key: 1,
            kind: "empty",
            title: "暂无日志"
          }))
        ])) : W("", !0)
      ]);
    };
  }
}, yh = {
  key: 0,
  class: "modal active"
}, bh = {
  class: "modal-dialog",
  style: { "max-width": "420px" }
}, kh = { class: "modal-body" }, $h = { class: "form-item" }, wh = { class: "form-item" }, xh = {
  key: 0,
  class: "form-error"
}, Sh = ["disabled"], Ch = {
  key: 1,
  class: "app"
}, Th = { class: "sidebar" }, Ah = { class: "nav" }, Oh = ["onClick"], Eh = { class: "nav-icon" }, Ph = { class: "sidebar-status" }, Ih = { class: "main" }, Rh = { class: "topbar" }, Nh = { class: "view-title" }, Mh = { class: "topbar-right" }, jh = {
  key: 0,
  class: "notif-badge"
}, Dh = { class: "user-chip" }, Fh = { class: "user-meta" }, Uh = { class: "user-name" }, Lh = { class: "user-role" }, Vh = {
  key: 0,
  class: "state-box state-box--error"
}, Hh = {
  class: "state-desc",
  style: { "font-family": "var(--mono)", "font-size": "11.5px" }
}, Kh = {
  key: 0,
  class: "modal active"
}, Bh = { class: "modal-dialog" }, qh = { class: "modal-head" }, Wh = { class: "modal-body" }, Jh = {
  key: 0,
  class: "empty"
}, zh = {
  key: 1,
  class: "empty"
}, Gh = {
  key: 2,
  class: "notif-list"
}, Yh = ["onClick"], Xh = { class: "notif-title" }, Qh = { class: "notif-content" }, Zh = { class: "notif-meta" }, ev = {
  __name: "App",
  setup(e) {
    const t = {
      dashboard: pu,
      documents: Dl,
      chat: Ud,
      personal: Gd,
      system: sf,
      tickets: sh,
      admin: _h
    }, s = {
      dashboard: "仪表盘",
      documents: "文档库",
      chat: "智能问答",
      personal: "个人中心",
      system: "系统状态",
      tickets: "工单中心",
      admin: "管理视图"
    }, n = Ce(() => t[F.view] || Dl), l = /* @__PURE__ */ H(null);
    yi((q) => (console.error("[kms-app] view error", q), l.value = String(q && q.message || q), !1));
    const o = Ce(() => {
      var xe;
      const q = Be.levelTag(Be.level()), Y = (xe = F.user) == null ? void 0 : xe.department;
      return Y ? `${q} · ${Y}` : q;
    }), a = Ce(() => s[F.view] || "知识服务平台"), r = /* @__PURE__ */ H(""), c = /* @__PURE__ */ H(""), f = /* @__PURE__ */ H(""), h = /* @__PURE__ */ H(!1);
    async function k() {
      if (f.value = "", !r.value.trim() || !c.value) {
        f.value = "请输入工号与密码";
        return;
      }
      h.value = !0;
      try {
        await G.login(r.value.trim(), c.value), await O(), c.value = "";
      } catch (q) {
        f.value = String(q.message || q);
      } finally {
        h.value = !1;
      }
    }
    async function R() {
      try {
        await G.logoutApi();
      } catch {
      }
      Pn(), F.view = "documents";
    }
    async function O() {
      var xe;
      try {
        F.user = await Me(() => G.me());
      } catch {
        Pn();
        return;
      }
      const [q, Y] = await Promise.all([
        G.levels().catch(() => ({ items: [] })),
        G.departments().catch(() => ({ items: [] }))
      ]);
      F.levels = Array.isArray(q) ? q : q.items || [], F.departments = Array.isArray(Y) ? Y : Y.items || [], C(), F.view === "dashboard" && !((xe = F.user) != null && xe.is_auditor) && (F.view = "documents");
    }
    async function C() {
      try {
        const q = await G.unreadCount();
        F.unread = Number(q.unread ?? q.count ?? 0) || 0;
      } catch {
        F.unread = 0;
      }
    }
    const j = /* @__PURE__ */ H(!1), D = /* @__PURE__ */ H([]), se = /* @__PURE__ */ H(!1);
    async function U() {
      j.value = !0, se.value = !0;
      try {
        const q = await G.notifications();
        D.value = q.items || [];
      } catch (q) {
        D.value = [], ee("通知加载失败：" + ((q == null ? void 0 : q.message) || q), "error");
      } finally {
        se.value = !1;
      }
    }
    async function L(q) {
      if (!q.is_read) {
        try {
          await G.markRead(q.id), q.is_read = !0;
        } catch {
        }
        C();
      }
      q.ticket_id && (j.value = !1, F.view = "tickets", F.jumpTicketId = Number(q.ticket_id));
    }
    async function I() {
      try {
        await G.markAllRead(), D.value.forEach((q) => {
          q.is_read = !0;
        }), C(), ee("已全部标记为已读", "ok");
      } catch (q) {
        ee("操作失败：" + ((q == null ? void 0 : q.message) || q), "error");
      }
    }
    async function X() {
      if (F.user)
        try {
          const q = await G.health();
          F.systemOk = (q == null ? void 0 : q.mysql) === "ok";
        } catch {
          F.systemOk = !1;
        }
    }
    const ve = Ce(
      () => F.systemOk === null ? "检测中…" : F.systemOk ? "运行正常" : "服务异常"
    );
    let _e = null, ye = null;
    function ot() {
      we(), C(), X(), _e = setInterval(C, 3e4), ye = setInterval(X, 1e4);
    }
    function we() {
      _e && (clearInterval(_e), _e = null), ye && (clearInterval(ye), ye = null);
    }
    st(Ml, (q) => {
      q ? ot() : (we(), F.systemOk = null, F.unread = 0, j.value = !1);
    });
    const Oe = /* @__PURE__ */ H(null);
    function Z() {
      var Y;
      const q = (Y = Oe.value) == null ? void 0 : Y.load;
      typeof q == "function" && q(), C(), X();
    }
    return st(
      () => jl.value.map((q) => q.view),
      (q) => {
        q.includes(F.view) || (F.view = "documents");
      }
    ), Ot(() => {
      (Ml.value || Wi()) && O();
    }), Bn(we), (q, Y) => {
      var xe;
      return ie(F).user ? (g(), y("div", Ch, [
        i("aside", Th, [
          Y[11] || (Y[11] = i("div", { class: "brand" }, "知识服务平台", -1)),
          i("nav", Ah, [
            (g(!0), y(V, null, ne(ie(jl), (J) => (g(), y("button", {
              key: J.view,
              class: ge(["nav-item", { active: ie(F).view === J.view }]),
              onClick: (le) => ie(F).view = J.view
            }, [
              i("span", Eh, _(J.icon), 1),
              nt(_(J.label), 1)
            ], 10, Oh))), 128))
          ]),
          i("div", Ph, [
            i("span", {
              class: ge(["status-pill", ie(F).systemOk === null ? "txt" : ie(F).systemOk ? "ok" : "fail"])
            }, [
              Y[10] || (Y[10] = i("span", { class: "dot" }, null, -1)),
              nt(_(ve.value), 1)
            ], 2)
          ])
        ]),
        i("main", Ih, [
          i("header", Rh, [
            i("h1", Nh, _(a.value), 1),
            i("div", Mh, [
              i("button", {
                class: "btn btn-ghost",
                title: "刷新当前视图",
                onClick: Z
              }, "↻"),
              i("button", {
                class: "btn btn-ghost bell-btn",
                title: "通知",
                onClick: U
              }, [
                Y[12] || (Y[12] = nt(" 🔔 ", -1)),
                ie(F).unread > 0 ? (g(), y("span", jh, _(ie(F).unread > 99 ? "99+" : ie(F).unread), 1)) : W("", !0)
              ]),
              i("div", Dh, [
                Y[13] || (Y[13] = i("span", { class: "user-avatar" }, "👤", -1)),
                i("div", Fh, [
                  i("span", Uh, _((xe = ie(F).user) == null ? void 0 : xe.username), 1),
                  i("span", Lh, _(o.value), 1)
                ])
              ]),
              i("button", {
                class: "btn btn-ghost",
                title: "退出登录",
                onClick: R
              }, "⏻")
            ])
          ]),
          (g(), y("div", {
            class: "view active",
            key: ie(F).view
          }, [
            l.value ? (g(), y("div", Vh, [
              Y[14] || (Y[14] = i("span", { class: "state-title" }, "视图加载异常", -1)),
              Y[15] || (Y[15] = i("span", { class: "state-desc" }, "侧栏与其他功能不受影响，可重试或切换其他栏目。", -1)),
              i("span", Hh, _(l.value), 1),
              i("button", {
                class: "btn",
                style: { "margin-top": "10px" },
                onClick: Y[2] || (Y[2] = (J) => l.value = null)
              }, "重试")
            ])) : (g(), pe(ur(n.value), {
              key: 1,
              ref_key: "viewRef",
              ref: Oe
            }, null, 512))
          ]))
        ]),
        j.value ? (g(), y("div", Kh, [
          i("div", {
            class: "modal-mask",
            onClick: Y[3] || (Y[3] = (J) => j.value = !1)
          }),
          i("div", Bh, [
            i("div", qh, [
              Y[16] || (Y[16] = i("h3", null, "通知", -1)),
              i("button", {
                class: "modal-close",
                onClick: Y[4] || (Y[4] = (J) => j.value = !1)
              }, "✕")
            ]),
            i("div", Wh, [
              i("div", { class: "notif-toolbar" }, [
                i("button", {
                  class: "btn btn-link",
                  onClick: I
                }, "全部标记为已读")
              ]),
              se.value ? (g(), y("div", Jh, "加载中…")) : D.value.length ? (g(), y("div", Gh, [
                (g(!0), y(V, null, ne(D.value, (J) => (g(), y("div", {
                  key: J.id,
                  class: ge(["notif-item", { unread: !J.is_read }]),
                  style: { cursor: "pointer" },
                  onClick: (le) => L(J)
                }, [
                  i("div", Xh, _(J.title), 1),
                  i("div", Qh, _(J.content || ""), 1),
                  i("div", Zh, _((J.created_at || "").replace("T", " ").slice(0, 19)) + " · " + _(J.ntype || ""), 1)
                ], 10, Yh))), 128))
              ])) : (g(), y("div", zh, "暂无通知"))
            ])
          ])
        ])) : W("", !0),
        (g(!0), y(V, null, ne(ie(Ps), (J, le) => (g(), y("div", {
          key: J.id,
          class: ge(["toast show", J.kind === "ok" ? "success" : J.kind === "error" ? "error" : ""]),
          style: es({ top: `${22 + le * 52}px` })
        }, _(J.text), 7))), 128))
      ])) : (g(), y("div", yh, [
        Y[9] || (Y[9] = i("div", { class: "modal-mask" }, null, -1)),
        i("div", bh, [
          Y[8] || (Y[8] = i("div", { class: "modal-head" }, [
            i("h3", null, "企业知识服务平台")
          ], -1)),
          i("div", kh, [
            i("form", {
              onSubmit: qi(k, ["prevent"])
            }, [
              i("div", $h, [
                Y[5] || (Y[5] = i("label", null, "工号", -1)),
                ke(i("input", {
                  "onUpdate:modelValue": Y[0] || (Y[0] = (J) => r.value = J),
                  class: "input",
                  autocomplete: "username",
                  placeholder: "如 20260019"
                }, null, 512), [
                  [ze, r.value]
                ])
              ]),
              i("div", wh, [
                Y[6] || (Y[6] = i("label", null, "密码", -1)),
                ke(i("input", {
                  "onUpdate:modelValue": Y[1] || (Y[1] = (J) => c.value = J),
                  class: "input",
                  type: "password",
                  autocomplete: "current-password"
                }, null, 512), [
                  [ze, c.value]
                ])
              ]),
              f.value ? (g(), y("div", xh, _(f.value), 1)) : W("", !0),
              i("button", {
                class: "btn btn-primary btn-block",
                disabled: h.value
              }, _(h.value ? "登录中…" : "登 录"), 9, Sh),
              Y[7] || (Y[7] = i("p", { class: "login-tip" }, "使用员工工号和密码登录。首次登录后请及时修改密码。", -1))
            ], 32)
          ])
        ])
      ]));
    };
  }
};
G.onUnauthorized = () => {
  Pn();
};
function sv(e) {
  const t = typeof e == "string" ? document.querySelector(e) : e;
  if (!t) throw new Error(`[kms-app] 挂载点不存在: ${e}`);
  const s = Aa(ev);
  return s.config.errorHandler = (n, l, o) => {
    console.error("[kms-app]", o, n), ee("界面异常：" + String(n && n.message || n), "error");
  }, s.mount(t), s;
}
export {
  G as api,
  sv as mount,
  ee as toast
};
