/* 前端安全策略契约测试：node --test
 *
 * 目的：在动 `app.js` 做视图拆分之前，先把**最不能错的安全判定**钉死。
 *
 * 每个断言都标注了它对齐的后端实现，前后端口径必须一致：
 *   管规则  ← gateway/routes_kms.py  manageable（委托 can_approve_document）
 */
import test from "node:test";
import assert from "node:assert/strict";

const {
  securityLevelOf,
  maxLevel,
  levelName,
  levelTag,
  isAdmin,
  isEmployee,
  canViewAdmin,
  canViewTickets,
  canManageDoc,
  writableRange,
} = await import("../../kms/web/js/core/policy.js");

const LEVELS = [
  { level: 0, name: "公开" },
  { level: 1, name: "秘密" },
  { level: 2, name: "机密" },
  { level: 3, name: "绝密" },
];

const emp = (lv, extra = {}) => ({
  id: 1, employee_no: "e1", username: "员工",
  security_level: lv, level: lv,       // 后端两者同源（to_public_dict）
  is_active: 1, department: "技术研发部", ...extra,
});

// ---------- 基础取值 ----------

test("securityLevelOf：优先 security_level，缺失回退 level，异常值归 0", () => {
  assert.equal(securityLevelOf({ security_level: 3, level: 3 }), 3);
  assert.equal(securityLevelOf({ level: 2 }), 2);              // 只有旧字段
  assert.equal(securityLevelOf({}), 0);
  assert.equal(securityLevelOf(null), 0);
  assert.equal(securityLevelOf(undefined), 0);
  assert.equal(securityLevelOf({ security_level: "x" }), 0);   // 非数字不抛错
});

test("maxLevel / levelName：空列表与未登记层级都不抛错", () => {
  assert.equal(maxLevel(LEVELS), 3);
  assert.equal(maxLevel([]), 0);
  assert.equal(maxLevel(null), 0);
  assert.equal(levelName(2, LEVELS), "机密");
  // 未登记层级的兜底用 **L 编号**（层级统称 L0-L3），不再是"层级9"——
  // 后者把"层级"和"文档密级"两套标签混在了一起。
  assert.equal(levelName(9, LEVELS), "L9");
});

// 层级（L0-L3）与文档密级（公开/…）是两套标签：顶栏、个人中心、用户列表
// 显示的是**人的层级**，必须走 levelTag；文档密级走 levelName。曾两者都走
// levelName，导致 L3 员工在顶栏被显示成"绝密"。
test("levelTag：人的层级用 L0-L3，与文档密级名区分", () => {
  assert.equal(levelTag(0), "L0");
  assert.equal(levelTag(3), "L3");
  assert.equal(levelTag(null), "L0");
  assert.equal(levelTag(undefined), "L0");
  // 同一个数字，两套标签给出不同结果——证明它们确实分开了
  assert.equal(levelName(3, LEVELS), "绝密");
  assert.equal(levelTag(3), "L3");
  assert.notEqual(levelName(3, LEVELS), levelTag(3));
});

test("入口可见性：管理域 L2 起，工单中心看在职", () => {
  assert.equal(canViewAdmin(emp(2)), true);
  assert.equal(canViewAdmin(emp(1)), false);
  assert.equal(canViewAdmin(null), false);
  assert.equal(canViewTickets(emp(0)), true);
  assert.equal(canViewTickets(emp(0, { is_active: 0 })), false);
});

test("角色判断：isAdmin 看 is_admin，isEmployee 看 role，null 不抛错", () => {
  assert.equal(isAdmin({ is_admin: 1 }), true);
  assert.equal(isAdmin({}), false);
  assert.equal(isAdmin(null), false);
  assert.equal(isEmployee({ role: "employee" }), true);
  assert.equal(isEmployee({ role: "guest" }), false);
  assert.equal(isEmployee(null), false);
});

// ---------- 管规则：能读才谈得上管理（docLevel <= 职级）+ 同部门 ----------

test("canManageDoc：管只能向下管，超出职级的文档不可管", () => {
  const u = emp(2);
  assert.equal(canManageDoc(0, u, "技术研发部", "技术研发部"), true);
  assert.equal(canManageDoc(2, u, "技术研发部", "技术研发部"), true);
  assert.equal(canManageDoc(3, u, "技术研发部", "技术研发部"), false); // 超出职级 ← 核心
});

test("canManageDoc：未定级文档按最高密级处理，仅 L3 可管", () => {
  assert.equal(canManageDoc(null, emp(3), "技术研发部", "技术研发部"), true);
  assert.equal(canManageDoc(null, emp(2), "技术研发部", "技术研发部"), false);
  assert.equal(canManageDoc(undefined, emp(2), "技术研发部", "技术研发部"), false);
});

test("canManageDoc：跨部门、停用、无部门 → 拒绝", () => {
  assert.equal(canManageDoc(0, emp(3), "技术研发部", "市场拓展部"), false);
  assert.equal(canManageDoc(0, emp(3, { is_active: 0 }), "技术研发部", "技术研发部"), false);
  assert.equal(canManageDoc(0, emp(3, { department: "" }), "技术研发部", ""), false);
});

// ---------- 上传入口的可写区间 ----------

test("writableRange：未登录 null；可写区间为 [职级, 最高密级]", () => {
  assert.equal(writableRange(null, LEVELS), null);
  assert.deepEqual(writableRange(emp(2), LEVELS), [2, 3]);
  assert.deepEqual(writableRange(emp(3), LEVELS), [3, 3]);
  assert.deepEqual(writableRange(emp(0), LEVELS), [0, 3]);
});

test("writableRange：所有层级（含 L0 公开）统一走自动审批，下限不收紧", () => {
  const range = writableRange(emp(0), LEVELS);
  assert.equal(range[0], 0, "L0 员工可从上传入口登记公开文档（上传后自动提交发布审批）");
  assert.equal(range.includes(0), true);
});
