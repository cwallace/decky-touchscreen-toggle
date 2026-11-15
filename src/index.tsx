import { callable, definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaHandPointer } from "react-icons/fa";
import { Content, type Status, type TouchApi } from "./Content";

const api: TouchApi = {
  getStatus: callable<[], Status>("get_status"),
  setEnabled: callable<[enabled: boolean], Status>("set_enabled"),
};
export default definePlugin(() => ({
  name: "Touchscreen Toggle",
  titleView: <div className={staticClasses.Title}>Touchscreen Toggle</div>,
  content: <Content api={api} />,
  icon: <FaHandPointer />,
  // Backend _unload handles restoration; closing the panel is NOT an unload.
  onDismount() {},
}));
