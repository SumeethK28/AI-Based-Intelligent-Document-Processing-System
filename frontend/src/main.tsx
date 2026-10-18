import { useState, useEffect } from "react";

import {
  LayoutDashboard,
  Files,
  ClipboardCheck,
  ChartNoAxesCombined,
  Settings,
  ArrowUpRight,
  ChevronRight,
  LogOut,
  Sun,
  Moon,
  ShieldCheck,
  Menu,
  X,
  Search,
  Upload,
} from "lucide-react";
import { api, Session } from "./api";
import { destinations } from "./presentation";

import {
  message,
  ActionContext,
  Button,
  Detail,
} from "./components";
import { createRoot } from "react-dom/client";
import { Overview } from "./Overview";
import { Documents } from "./Documents";
import { MyWork } from "./MyWork";
import { Insights } from "./Insights";
import { Administration, Account, AccessScreen } from "./Administration";
import "./styles.css";

function App() {
  const [session, setSession] = useState<Session>(),
    [ready, setReady] = useState(false),
    [page, setPage] = useState("Overview"),
    [documentView, setDocumentView] = useState("Repository"),
    [documentVisit, setDocumentVisit] = useState(0),
    [documentSearch, setDocumentSearch] = useState(""),
    [searchDraft, setSearchDraft] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [nav, setNav] = useState(false),
    [dark, setDark] = useState(localStorage.getItem("idp-theme") === "dark");
  useEffect(() => {
    api<Session>("/session")
      .then(setSession)
      .catch(() => {})
      .finally(() => setReady(true));
    const end = () => {
      setSession(undefined);
      setPage("Overview");
      setDocumentView("Repository");
      setDocumentSearch("");
      setSearchDraft("");
    };
    window.addEventListener("idp-session-ended", end);
    return () => window.removeEventListener("idp-session-ended", end);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    localStorage.setItem("idp-theme", dark ? "dark" : "light");
  }, [dark]);
  const run = async (job: () => Promise<unknown>) => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await job();
      setNotice("Action completed. The latest saved information is shown.");
      window.dispatchEvent(new Event("idp-refresh"));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  const permissions = session?.permissions ?? [],
    links = destinations.map((item,index) => [item.name,
      [LayoutDashboard, Files, ClipboardCheck, ChartNoAxesCombined, Settings][index],item.permission] as const);
  const navigate = (v: string) => {
    if (v === "Documents") setDocumentVisit((value) => value + 1);
    setDocumentView("Repository");
    setDocumentSearch("");
    setPage(v);
    setError("");
    setNotice("");
    setNav(false);
  };
  if (!ready)
    return <div className="startup">Opening Document Operations…</div>;
  return (
    <ActionContext.Provider value={{ run, busy, permissions }}>
      {!session ? (
        <div className="signin">
          <div className="signin-story">
            <div className="brand">
              <span className="brand-mark">d</span>Document Operations
            </div>
            <span className="eyebrow">LESS FRICTION. MORE CLARITY.</span>
            <h1>
              Every document.
              <br />A clearer decision.
            </h1>
            <p>
              A focused workspace for extracting information, verifying evidence
              and resolving exceptions.
            </p>
            <div className="signin-proof">
              <ShieldCheck />
              Evidence-grounded. Human-reviewed.
            </div>
          </div>
          <AccessScreen error={error} onSignedIn={(value) => {
            setPage("Overview"); setDocumentView("Repository"); setDocumentSearch(""); setSearchDraft(""); setSession(value);
          }} />
        </div>
      ) : (
        <div className="app-shell">
          <aside className={nav ? "sidebar expanded" : "sidebar"}>
            <div className="brand">
              <span className="brand-mark">d</span>
              <span>
                Document
                <br />
                Operations
              </span>
              <button
                className="icon-button mobile-close"
                onClick={() => setNav(false)}
                aria-label="Close navigation"
              >
                <X size={18} />
              </button>
            </div>
            <div className="workspace-label">YOUR WORKSPACE</div>
            {permissions.includes("intake") && (
              <Button
                primary
                aria-label="Upload document"
                onClick={() => {
                  navigate("Documents");
                  setDocumentView("Upload");
                }}
              >
                <Upload size={16} />
                Upload
              </Button>
            )}
            <nav aria-label="Main navigation">
              {links
                .filter(([, , permission]) => permissions.includes(permission))
                .map(([name, Icon]) => (
                  <button
                    key={name}
                    className={page === name ? "nav-item active" : "nav-item"}
                    aria-current={page === name ? "page" : undefined}
                    onClick={() => navigate(name)}
                  >
                    <Icon size={19} />
                    <span>{name}</span>
                    {page === name && <ChevronRight size={15} />}
                  </button>
                ))}
            </nav>
            <div className="sidebar-bottom">
              <div className="prototype-note">
                <ShieldCheck size={18} />
                <p>
                  Document workspace<small>Clear information. Accountable decisions.</small>
                </p>
              </div>
              <div className="account">
                <div className="avatar">
                  {session.username.slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <strong>{session.username}</strong>
                  <small>{session.role}</small>
                </div>
              </div>
              <Detail title="My account">
                <p className="footnote">{session.departments.join(", ")}</p>
                <Account />
              </Detail>
              <Button
                onClick={() =>
                  run(async () => {
                    await api("/logout", {});
                    setSession(undefined);
                    setPage("Overview");
                    setDocumentView("Repository");
                    setDocumentSearch("");
                    setSearchDraft("");
                  })
                }
              >
                <LogOut size={15} />
                Sign out
              </Button>
            </div>
          </aside>
          <div className="workspace">
            <header>
              <div className="breadcrumb">
                <button
                  className="icon-button mobile-menu"
                  onClick={() => setNav(!nav)}
                  aria-label="Open navigation"
                >
                  <Menu size={20} />
                </button>
                <span>Workspace</span>
                <ChevronRight size={14} />
                <strong>{page}</strong>
              </div>
              {permissions.includes("documents") && (
                <form
                  className="header-search"
                  onSubmit={(e) => {
                    e.preventDefault();
                    navigate("Documents");
                    setDocumentSearch(searchDraft);
                  }}
                >
                  <Search size={16} />
                  <input
                    aria-label="Search workspace documents"
                    placeholder="Search documents, numbers, parties…"
                    value={searchDraft}
                    onChange={(e) => setSearchDraft(e.target.value)}
                  />
                  <button
                    type="submit"
                    aria-label="Search documents from header"
                  >
                    <ArrowUpRight size={16} />
                  </button>
                </form>
              )}
              <div className="actions">
                <span className="local-label">
                  <i />
                  Local workspace
                </span>
                <button
                  className="icon-button"
                  onClick={() => setDark(!dark)}
                  aria-label={dark ? "Use light mode" : "Use dark mode"}
                >
                  {dark ? <Sun size={18} /> : <Moon size={18} />}
                </button>
                <span className="header-avatar" title={session.username}>
                  {session.username.slice(0, 2).toUpperCase()}
                </span>
              </div>
            </header>
            <main>
              {busy && (
                <div className="busy-bar" role="status">
                  Working… Please keep this window open. Saved batch progress
                  remains recoverable.
                </div>
              )}
              {error && (
                <div className="notice error" role="alert">
                  {error}
                  <button
                    className="icon-button"
                    onClick={() => setError("")}
                    aria-label="Dismiss error"
                  >
                    <X size={16} />
                  </button>
                </div>
              )}
              {notice && (
                <div className="notice good" role="status">
                  {notice}
                </div>
              )}
              {page === "Overview" ? (
                <Overview navigate={navigate} session={session} />
              ) : page === "Documents" ? (
                <Documents
                  key={documentVisit}
                  initialView={documentView}
                  initialSearch={documentSearch}
                />
              ) : page === "My Work" ? (
                <MyWork session={session} />
              ) : page === "Insights" ? (
                <Insights />
              ) : (
                <Administration />
              )}
              <footer>
                Document Operations{" "}
                <span>
                  Preliminary checks support review. They never authorize
                  payments or legal execution.
                </span>
              </footer>
            </main>
          </div>
        </div>
      )}
    </ActionContext.Provider>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
