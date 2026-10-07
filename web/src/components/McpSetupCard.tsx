/** Connecting an agent to the platform over MCP, as one prompt to paste.
 *
 *  **The prompt carries no token, on purpose.** It is pasted into an agent's
 *  chat, and a chat is stored by the agent's vendor and in a transcript on
 *  disk — a token in it would be a credential in two places nobody manages.
 *  So the prompt makes the agent ask the user to save the token in
 *  `~/.config/kicad-library/token` from their OWN terminal, with input hidden,
 *  and the MCP server reads it from there
 *  (`api/app/services/mcp_server/server.py`). The token is shown BESIDE the
 *  prompt, masked, with its own Copy button: that is what the user pastes
 *  into the terminal when the agent asks.
 *
 *  The agent downloads the server script from `GET /api/agent/mcp-server` with
 *  that token, so the download doubles as the token check. Every command in
 *  the prompt was run end to end on macOS (zsh and bash) before it was written
 *  here: change one and run it again.
 *
 *  `me` comes from the Account page, which shares it with
 *  `AccountSecurityCard` — a token created or revoked there shows up here
 *  without a reload.
 */
import { useEffect, useState } from "react";

import {
  errorMessage,
  getKicadConfig,
  isAbortError,
  type PlatformUser,
} from "../api";
import Field from "./Field";
import { CopyButton, ErrorBanner, Spinner } from "./Ui";

/** Where the setup puts things. The MCP server's own defaults must match. */
const TOKEN_FILE = "~/.config/kicad-library/token";
const SCRIPT_FILE = "~/.local/share/kicad-library/kicad_library_mcp.py";

/** The text the user gives to the agent. Written FOR the agent: steps it can
 *  run, and the rules it must keep about the token. `String.raw` keeps the
 *  shell's `\n` as typed; `~~~` fences because a raw template cannot hold a
 *  backtick. */
export function mcpSetupPrompt(base: string, accountUrl: string): string {
  return String.raw`Set up the 7Sigma KiCad library platform as an MCP server on this computer. Do the steps in order.

Facts:
- Platform API: ${base}
- MCP server name: kicad-library
- Token file: ${TOKEN_FILE}
- Server script: ${SCRIPT_FILE}
- The commands are for macOS and Linux. On Windows, write PowerShell commands that do the same work, and obey the same token rules.

Token rules:
- Do not ask me to paste my API token into this chat.
- Do not print, log or echo the token. Do not type it into a command, and do not write it into a config file or a repository. The commands below read it from the token file.
- If I paste the token into the chat, write it to the token file and do not repeat it. Then tell me that this chat now holds the token, and that I can revoke it and make a new one on the Account page.

1. Make sure that uv is installed: run "uv --version". If uv is missing, ask me before you install it. Use the official instructions at https://docs.astral.sh/uv/getting-started/installation/

2. Tell me to save my token. I copy it from the Account page (${accountUrl}, card "Agents (MCP)", button "Copy token"). Then I run this command in my own terminal, not through you. It does not show the token on the screen:

~~~
bash -c 'mkdir -p ~/.config/kicad-library && chmod 700 ~/.config/kicad-library && printf "Paste the token, then press Enter: " && read -rs t && (umask 077 && printf "%s\n" "$t" > ~/.config/kicad-library/token) && chmod 600 ~/.config/kicad-library/token && echo && echo "Token saved."'
~~~

On Windows, give me a PowerShell command that reads the token with Read-Host -AsSecureString and writes it to $HOME\.config\kicad-library\token. Wait until I tell you that the token is saved.

3. Download the server script. This also tests the token:

~~~
mkdir -p ~/.local/share/kicad-library && curl -fsS -w '%{http_code}\n' -H "Authorization: Bearer $(cat ~/.config/kicad-library/token)" -o ~/.local/share/kicad-library/kicad_library_mcp.py ${base}/api/agent/mcp-server
~~~

200 means that the token is good. 401 means that the token is wrong or revoked: go back to step 2.

4. Register the server.

Claude Code, for all my projects:

~~~
claude mcp add kicad-library --scope user -e KICAD_API_URL=${base} -- "$(command -v uv)" run --quiet --script "$HOME/.local/share/kicad-library/kicad_library_mcp.py"
~~~

If kicad-library is already registered, remove it first with "claude mcp remove kicad-library --scope user".

Another MCP client: add this stdio server to its config. Replace the two paths with absolute paths. Do not add the token, because the server reads the token file.

~~~json
{
  "mcpServers": {
    "kicad-library": {
      "command": "/absolute/path/to/uv",
      "args": ["run", "--quiet", "--script", "/absolute/path/to/kicad_library_mcp.py"],
      "env": { "KICAD_API_URL": "${base}" }
    }
  }
}
~~~

5. Check the connection. In Claude Code, run "claude mcp list". The kicad-library line must show "Connected". Then tell me to start a new session, because an agent loads its MCP tools when a session starts.

After the setup:
- The tools read and write the live platform as my user. Every write publishes immediately.
- Before you do library work, call list_skills. Then read the skill for the task with get_skill. The skills hold the library conventions.
- To update the server script, do step 3 again.
`;
}

function masked(token: string): string {
  return `${token.slice(0, 7)}${"•".repeat(16)}`;
}

export default function McpSetupCard({ me }: { me: PlatformUser | null }) {
  const [base, setBase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<number | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    getKicadConfig(ctrl.signal)
      .then((c) => setBase(c.public_base_url.replace(/\/+$/, "")))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  const tokens = me?.tokens ?? [];
  const token = tokens.find((t) => t.id === pick) ?? tokens[0] ?? null;
  // The page the reader is on IS the Account page, at whatever address they
  // reached it by — the public base URL names the API, which locally is not
  // where the UI is served.
  const accountUrl = window.location.origin + window.location.pathname;
  const prompt = base ? mcpSetupPrompt(base, accountUrl) : "";

  return (
    <div className="card pad">
      <h2>Agents (MCP)</h2>
      <ErrorBanner message={error ?? ""} />
      <p className="muted">
        Claude Code, or any other agent that speaks MCP, reaches the platform's tools through a
        small server that runs on your computer. The agent acts as you: it reads the whole
        platform, and its library edits publish at once.
      </p>
      <ol className="kicad-steps">
        <li>
          Copy the setup prompt and give it to the agent on the computer where the agent runs.
        </li>
        <li>
          The agent asks you to save your token. It gives you a command to run in your own
          terminal, and the command hides what you paste. The token does not go into the chat.
        </li>
        <li>
          Copy your token below and paste it into that command. The agent then downloads the
          server, registers it and checks the connection.
        </li>
      </ol>

      <h3>Setup prompt</h3>
      {base === null && !error ? (
        <Spinner label="Loading" />
      ) : (
        <>
          <div className="btn-row">
            <CopyButton value={prompt} label="Copy the prompt" className="btn btn-primary" />
          </div>
          <pre className="code-block code-block-prompt">{prompt}</pre>
          <p className="muted dim">
            The prompt contains no token. It is safe to paste into any chat.
          </p>
        </>
      )}

      <h3>Your token</h3>
      {me === null ? (
        <Spinner label="Loading account" />
      ) : token === null ? (
        <p className="muted">
          You have no API token. Create one under <b>Password and API tokens</b> above, then copy
          it from here.
        </p>
      ) : (
        <>
          {tokens.length > 1 ? (
            <div className="field-row">
              <Field label="Token for this computer">
                <select
                  className="text"
                  value={token.id}
                  onChange={(e) => {
                    setPick(Number(e.target.value));
                    setShown(false);
                  }}
                >
                  {tokens.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label || t.prefix}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          ) : null}
          <div className="user-url-row">
            <span className="muted">{token.label || "token"}</span>
            <code className="user-url">{shown ? token.token : masked(token.token)}</code>
            <button type="button" className="btn btn-sm" onClick={() => setShown(!shown)}>
              {shown ? "Hide" : "Show"}
            </button>
            <CopyButton value={token.token} label="Copy token" />
          </div>
          <p className="muted dim">
            Give each computer its own token: you can then revoke one computer without breaking the
            others. Revoking a token stops the MCP server that uses it at once.
          </p>
        </>
      )}

      <details>
        <summary className="muted">Working inside the KiCad-Lib repository</summary>
        <p className="muted">
          The repository's <span className="mono">.mcp.json</span> already registers{" "}
          <span className="mono">kicad-library</span> from its own copy of the server, so you do
          not need the prompt there. Save the token in{" "}
          <span className="mono">{TOKEN_FILE}</span> as above, or set{" "}
          <span className="mono">KICAD_MCP_TOKEN</span> in the <span className="mono">env</span>{" "}
          block of <span className="mono">.claude/settings.local.json</span>, which git ignores.
          If you also ran the prompt on that computer, <span className="mono">claude mcp list</span>{" "}
          inside the repository warns that <span className="mono">kicad-library</span> is defined
          in two scopes. Both entries reach the same platform with the same token. The skill documents are copied to <span className="mono">.claude/skills/</span>, and
          the repository's <span className="mono">CLAUDE.md</span> tells the agent how to keep
          the copies current.
        </p>
      </details>
    </div>
  );
}
