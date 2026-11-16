import { callable, definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { Content, type RuleResult, type Status, type TouchApi } from "./Content";
import { createAutomation } from "./automation";

const api: TouchApi = {
  getStatus: callable<[], Status>("get_status"),
  setEnabled: callable<[enabled: boolean], Status>("set_enabled"),
  getSettings: callable<[], RuleResult>("get_settings"),
  setAutoEnabled: callable<[auto: boolean], RuleResult>("set_auto_enabled"),
  setException: callable<[appid: string, keep: boolean], RuleResult>("set_exception"),
  reportGameState: callable<[appid: string | null], RuleResult>("report_game_state"),
  releaseAuto: callable<[], RuleResult>("release_auto"),
};
export default definePlugin(() => {
  // Plugin lifetime, NOT Content lifetime: works with the QAM panel closed.
  const monitor = createAutomation(api);
  return {
    name: "Touchscreen Toggle",
    titleView: <div className={staticClasses.Title}>Touchscreen Toggle</div>,
    content: <Content api={api} monitor={monitor} />,
    // Font Awesome Free 5.15.4, Fonticons, Inc. — CC BY 4.0.
    // https://fontawesome.com/license/free (unchanged hand-pointer artwork)
    icon: <svg viewBox="0 0 448 512" width="1em" height="1em" fill="currentColor" aria-hidden="true" focusable="false">
      <path d="M448 240v96c0 3.084-.356 6.159-1.063 9.162l-32 136C410.686 499.23 394.562 512 376 512H168a40.004 40.004 0 0 1-32.35-16.473l-127.997-176c-12.993-17.866-9.043-42.883 8.822-55.876 17.867-12.994 42.884-9.043 55.877 8.823L104 315.992V40c0-22.091 17.908-40 40-40s40 17.909 40 40v200h8v-40c0-22.091 17.908-40 40-40s40 17.909 40 40v40h8v-24c0-22.091 17.908-40 40-40s40 17.909 40 40v24h8c0-22.091 17.908-40 40-40s40 17.909 40 40zm-256 80h-8v96h8v-96zm88 0h-8v96h8v-96zm88 0h-8v96h8v-96z" />
    </svg>,
    onDismount() { void monitor.dispose(); },
  };
});
