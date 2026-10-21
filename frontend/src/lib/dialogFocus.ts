import type { KeyboardEvent } from "react";

/** Keep Tab within the modal rather than moving focus to browser chrome. */
export function trapDialogFocus(event: KeyboardEvent<HTMLDialogElement>): void {
  if (event.key !== "Tab" || event.altKey || event.ctrlKey || event.metaKey) return;
  const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
    'button, input, select, textarea, summary, a[href], [tabindex]:not([tabindex="-1"])',
  )).filter(element => !element.matches(":disabled") && element.tabIndex >= 0
    && element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden"
    && !element.closest("[inert]"));
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (!first || !last) {
    event.preventDefault();
    event.currentTarget.focus();
  } else if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
