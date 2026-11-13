/* ===== js/core/policy.js · 前端安全策略（纯函数）=====
 *
 * 只放**安全判定**：不碰 DOM、不读写任何全局 state，输入全部走显式参数。
 * 这是它能被 `node --test` 直接 import 测试的前提。
 *
 * 为什么先抽这一层
 * ----------------
 * `app.js`（约 2400 行）是经典脚本，无法被 import，长期零测试覆盖；
 * 而其中**最不能错的恰好就是这些 BLP 判定**。把纯逻辑先钉死，
 * 后续做视图拆分（docs/frontend_architecture.md §6 步骤 3）才有回归参照系——
 * 否则在零覆盖代码上做结构改动，行为差异无从发现。
 *
 * 术语（务必准确，本项目历史上写错过）
 * ------------------------------------
 * BLP 两条规则，方向相反，混用会写出反向的权限判断：
 *   不上读（no read up）：能读 doc_level <= 职级      —— canRead / manageable 用
 *   不下写（no write down）：能写 doc_level >= 职级   —— canWrite 用
 * 即：读只能往下读，写只能往上写。
 *
 * 依赖方向：本层属 core，禁止反向 import ui / sdk。
 */

/** 员工安全职级。
 *
 * 后端 /auth/me 同时给 `security_level` 与 `level`，后者是前者的兼容别名，
 * 两者同源（kms/security.py:319-320 to_public_dict），取任一等价。
 * 这里显式优先 `security_level`，避免依赖两个字段谁先被填上。
 */
export function securityLevelOf(u) {
  if (!u) return 0;
  const lv = u.security_level != null ? u.security_level : u.level;
  const n = Number(lv);
  return Number.isFinite(n) ? n : 0;
}

/** 可用密级上限。levels 来自 /admin/levels（固定 L0-L3）；空列表时回退 0。 */
export function maxLevel(levels) {
  const arr = Array.isArray(levels) ? levels : [];
  return arr.length ? Math.max(...arr.map((l) => Number(l.level) || 0)) : 0;
}

/** 密级名称；未登记的层级回退 "层级N"，不会抛错。 */
/** **文档密级名**（公开/秘密/机密/绝密），来自 /admin/levels 的 name。
 *  用于文档自身的 classification，例如列表密级列、上传密级下拉框。 */
export function levelName(level, levels) {
  const arr = Array.isArray(levels) ? levels : [];
  const hit = arr.find((l) => Number(l.level) === Number(level));
  return hit ? hit.name : `L${level}`;
}

/** **人的层级编号**（L0-L3）——与 levelName 是两套标签，不可混用：
 *  「层级」说的是**员工职级**（顶栏、个人中心、用户列表、审批人后缀），
 *  「密级」说的是**文档**（上传下拉框、列表密级列）。
 *  曾把两者都走 levelName，导致顶栏把 L3 员工显示成「绝密」。 */
export function levelTag(level) {
  return `L${Number(level) || 0}`;
}

// ---- 角色 / 入口可见性 ----

export function isAdmin(u) {
  return !!u && !!u.is_admin;
}

export function isEmployee(u) {
  return !!u && u.role === "employee";
}

/** 可进入管理域：安全职级 L2 及以上 */
export function canViewAdmin(u) {
  return !!u && securityLevelOf(u) >= 2;
}

/** 可进入工单中心：所有在职员工（系统中不存在管理员概念，每人都可发起工单） */
export function canViewTickets(u) {
  return !!u && !!u.is_active;
}

/** 文档管理权限（能否改密级 / 发布 / 删除）。
 *
 * 对齐后端 `gateway/routes_kms.py manageable`（委托 can_approve_document）：
 *   1. 员工在职且有部门
 *   2. docLevel <= 职级（**能读才谈得上管理**，方向是"不上读"）
 *   3. 部门匹配：员工部门 IN 归属部门数组，或数组含「不限部门」（"*"）；
 *      空数组 = 未登记部门 → 无人可管理（fail-closed）
 *   4. 未定级（level 为 null）时按最高密级处理：仅 L3 可管
 *   5. 上传者本人（isUploader=true）对自己上传的文档始终可管理，
 *      即使归属到其他部门——与后端 manageable 的 granted_by 例外对齐。
 */
export function canManageDoc(docLevel, u, docDepts, userDept, isUploader = false) {
  if (!u || !u.is_active) return false;
  // 上传者例外：本人上传的文档，不论归属部门，始终可管理
  if (isUploader) {
    if (docLevel == null) return securityLevelOf(u) === 3;
    const lv = Number(docLevel);
    return lv >= 0 && lv <= securityLevelOf(u);
  }
  // 统一解析为数组（兼容旧数据单字符串 / JSON 字符串 / 数组）
  let depts = docDepts;
  if (typeof depts === "string") {
    try { depts = JSON.parse(depts); } catch { depts = depts ? [depts] : []; }
  }
  if (!Array.isArray(depts)) depts = depts ? [depts] : [];
  const ud = userDept || "";
  // 空数组 = 未登记部门 → 无人可管理（fail-closed）。
  // "*" = 显式「不限部门」→ 不校验归属部门（与后端 manageable 对齐）。
  if (!depts.length) return false;
  if (!depts.includes("*") && !depts.includes(ud)) return false;
  if (docLevel == null) return securityLevelOf(u) === 3;     // 未定级按最高密级
  const lv = Number(docLevel);
  return lv >= 0 && lv <= securityLevelOf(u);
}

/** 上传入口的可写密级区间 [min, max]；不可写者返回 null。
 *
 * 与后端 BLP 一致：可写区间为 [本人职级, 系统最高密级]（不下写）。
 * **所有密级层级（含 L0 公开）统一规则**：上传后一律自动提交发布审批，
 * 由系统按目标密级+归属部门匹配审批人双人把关，不区分"L0 走工单、
 * 其余直传"两条路径。曾把下限收紧到 1（"L0 发布一律走工单"），但
 * doc_upload 工单模块从未注册，反而把公开层堵成"只出不进"的死锁：
 * L0 员工被 UI 挡住，L1+ 员工受 BLP 下写限制同样无法登记 L0。
 */
export function writableRange(u, levels) {
  if (!u) return null;
  const minL = securityLevelOf(u);
  const maxL = maxLevel(levels);
  // 无可写层级：本人职级已超过系统最高密级（理论上不会出现，防御性检查）
  if (minL > maxL) return null;
  return [minL, maxL];
}
