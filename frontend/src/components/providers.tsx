"use client";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { request } from "@/lib/api";
import type { Connection, Message, Player, Snapshot } from "@/lib/types";

type Account = { username: string; leagueId: string };
type Store = {
  account: Account | null;
  ready: boolean;
  connect: (connection: Connection) => void;
  selectLeague: (id: string) => void;
  disconnect: () => void;
  selectedPlayer: Player | null;
  selectPlayer: (p: Player | null) => void;
  messages: Message[];
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
};
const Context = createContext<Store | null>(null);
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            gcTime: 30 * 60_000,
            retry: 1,
            refetchOnWindowFocus: true,
          },
        },
      }),
  );
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [selectedPlayer, selectPlayer] = useState<Player | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const generation = useRef(0);
  const renderGeneration = generation.current;
  useEffect(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem("fanedge-account") || "null",
      );
      if (
        typeof saved?.username === "string" &&
        typeof saved?.leagueId === "string"
      )
        setAccount(saved);
    } catch {
      /* corrupt preferences are ignored */
    }
    setReady(true);
  }, []);
  function save(value: Account | null) {
    generation.current += 1;
    setAccount(value);
    setMessages([]);
    selectPlayer(null);
    if (value) localStorage.setItem("fanedge-account", JSON.stringify(value));
    else localStorage.removeItem("fanedge-account");
  }
  const store: Store = {
    account,
    ready,
    selectedPlayer,
    selectPlayer,
    messages,
    setMessages: (update) => {
      // An answer started in another league must never enter this conversation.
      if (generation.current === renderGeneration) setMessages(update);
    },
    connect: (connection) => {
      client.setQueryData(["leagues", connection.username], connection);
      save({
        username: connection.username,
        leagueId: connection.leagues[0].id,
      });
    },
    selectLeague: (id) => {
      if (account) save({ ...account, leagueId: id });
    },
    disconnect: () => {
      save(null);
      client.clear();
    },
  };
  return (
    <QueryClientProvider client={client}>
      <Context.Provider value={store}>{children}</Context.Provider>
    </QueryClientProvider>
  );
}
export function useFanEdge() {
  const context = useContext(Context);
  if (!context) throw new Error("Missing FanEdge provider");
  return context;
}
export function useLeague() {
  const { account } = useFanEdge();
  const path = account
    ? `/api/leagues/${encodeURIComponent(account.leagueId)}`
    : "";
  const suffix = `?username=${encodeURIComponent(account?.username || "")}`;
  const query = useQuery({
    queryKey: ["snapshot", account?.username, account?.leagueId],
    queryFn: () => request<Snapshot>(`${path}/snapshot${suffix}`),
    enabled: !!account,
    refetchInterval: (q) => (q.state.data?.meta.refreshing ? 1500 : 60_000),
  });
  return { ...query, endpoint: (route: string) => `${path}/${route}${suffix}` };
}
