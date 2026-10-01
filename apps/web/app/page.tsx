import { redirect } from "next/navigation";

// The GridForge planner is served as a static app from /public/planner.
export default function Page() {
  redirect("/planner/index.html");
}
