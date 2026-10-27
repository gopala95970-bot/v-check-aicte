export const state = { user: null, meta: null, queueCount: null };
export const isStaff = () => state.user && (state.user.role === "reviewer" || state.user.role === "admin");
export const isRole = (...r) => state.user && r.includes(state.user.role);
export const can = (perm) => !!state.user && state.user.permissions.includes(perm);
