export function bootstrap(): boolean {
  return true;
}

declare global {
  interface Window {
    openTaskpane?: () => boolean;
  }
}

window.openTaskpane = bootstrap;
