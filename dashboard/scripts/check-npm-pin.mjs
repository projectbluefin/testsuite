// renovate.json's constraints.npm sets the npm version Renovate writes
// dashboard/package-lock.json with. It must match the npm CI runs, which is
// the one bundled with Node, so a Node major can move it. Renovate doesn't
// offer updates to the pin, so this fails the Node major PR's dashboard
// build until someone raises it. Enforced in CI only, so a local build on
// another npm isn't blocked.
import { readFileSync } from "node:fs";

const running = (process.env.npm_config_user_agent ?? "").match(
  /\bnpm\/(\d+)\.\d+\.\d+/,
);
if (!process.env.CI || !running) process.exit(0);

const config = JSON.parse(
  readFileSync(new URL("../../renovate.json", import.meta.url), "utf8"),
);
const pin = config.constraints?.npm ?? "";
const version = running[0].slice(4);

if (pin.match(/\d+/)?.[0] !== running[1]) {
  console.error(
    `renovate.json has constraints.npm "${pin}", but CI runs npm ${version}. ` +
      `Set constraints.npm to "^${version}" in this pull request.`,
  );
  process.exit(1);
}
console.log(`renovate.json constraints.npm "${pin}" matches npm ${version}.`);
