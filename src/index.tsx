import { callable, definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaHandPointer } from "react-icons/fa";
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
    icon: <FaHandPointer />,
    onDismount() { void monitor.dispose(); },
  };
});
