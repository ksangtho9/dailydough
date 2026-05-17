/**
 * Admin Mode Framework
 * 
 * Admin mode is driven by API (user.is_admin from /api/auth/me).
 * Dev mode is a localStorage convenience toggle for client-side UI features only.
 */

const DEBUG_UI_KEY = "dashboard_debug_ui";

// Cache for admin status (updated by components that call refreshAdminStatus)
let cachedAdminStatus: boolean | null = null;

/**
 * Check if debug UI mode is enabled (reads from localStorage).
 * This is a non-security convenience toggle for client-side features only.
 */
export function isDevMode(): boolean {
  if (typeof window === "undefined") return false;
  if (!isAdminMode()) return false;
  const debugUi = localStorage.getItem(DEBUG_UI_KEY);
  return debugUi === "true";
}

/**
 * Check if admin mode is enabled.
 * Reads from cached admin status (set by refreshAdminStatus).
 * Returns false if status hasn't been fetched yet.
 */
export function isAdminMode(): boolean {
  return cachedAdminStatus === true;
}

/**
 * Refresh admin status from API.
 * Call this on app load or after login to update the cached admin status.
 */
export async function refreshAdminStatus(): Promise<boolean> {
  try {
    const { getCurrentUser } = await import("./api");
    const user = await getCurrentUser();
    cachedAdminStatus = user.is_admin;
    if (!user.is_admin) {
      localStorage.removeItem(DEBUG_UI_KEY);
    }
    return user.is_admin;
  } catch (error) {
    cachedAdminStatus = false;
    return false;
  }
}

/**
 * Require admin mode - throws error if not in admin mode.
 * Use this for critical operations that must have admin access.
 */
export function requireAdminMode(): void {
  if (!isAdminMode()) {
    throw new Error("Admin mode required");
  }
}

/**
 * Get admin mode status (for debugging/logging)
 */
export function getAdminModeStatus(): { isAdmin: boolean; isDev: boolean } {
  return {
    isAdmin: isAdminMode(),
    isDev: isDevMode(),
  };
}

/**
 * Set cached admin status (for testing or manual override).
 * Normally you should use refreshAdminStatus() instead.
 */
export function setCachedAdminStatus(isAdmin: boolean): void {
  cachedAdminStatus = isAdmin;
}




