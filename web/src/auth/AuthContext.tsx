import {
  createContext,
  Fragment,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "../supabase";
import { setAccountStorageScope } from "../accountStorage";

type AuthContextValue = {
  session: Session | null;
  user: User | null;
  loading: boolean;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }

    let active = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (active) {
        setAccountStorageScope(data.session?.user.id ?? null);
        setSession(data.session);
        setLoading(false);
      }
    }).catch(() => { if (active) { setAccountStorageScope(null); setLoading(false); } });

    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setAccountStorageScope(nextSession?.user.id ?? null);
      setSession(nextSession);
      setLoading(false);
    });

    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      user: session?.user ?? null,
      loading,
      signOut: async () => {
        if (supabase) {
          const { error } = await supabase.auth.signOut();
          if (error) throw error;
        }
        setAccountStorageScope(null);
      },
    }),
    [loading, session],
  );

  return <AuthContext.Provider value={value}><Fragment key={session?.user.id ?? "signed-out"}>{children}</Fragment></AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
