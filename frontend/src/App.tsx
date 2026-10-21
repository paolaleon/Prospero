import AgentList from "./components/AgentList";
import Editor from "./components/Editor";
import { useRoute } from "./lib/router";

export default function App() {
  const route = useRoute();
  return route.page === "editor" ? <Editor key={route.agentId} agentId={route.agentId} /> : <AgentList />;
}
