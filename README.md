# ryot-plex-relay

A small relay that makes Plex webhooks work with [Ryot](https://github.com/IgnisDa/ryot)'s **Plex Sink** integration, by removing the poster image that Ryot rejects.

> **Written with AI.** This project was written by [Claude](https://claude.ai) (Anthropic's Claude Code) while debugging my own Ryot + Plex setup, with me directing the work and testing it against my own server. It is not an official Ryot or Plex project and I'm not affiliated with either. The code is small (`relay.py`, about 90 lines, standard library only), so please read it before you run it.

## Why this exists

When I pointed Plex's webhooks at Ryot's Plex Sink, watches were not tracked correctly. Ryot answered HTTP 400 to every `media.play` event:

```
Request body didn't contain valid UTF-8: invalid utf-8 sequence of 1 bytes from index 3688
```

What I found:

- Plex sends each webhook as `multipart/form-data`: a JSON `payload` part, plus, on `media.play` events, a binary poster image (`thumb`) part.
- Ryot's webhook endpoint reads the whole request body as text, so the image makes it reject every play event.

That matches [#1793](https://github.com/IgnisDa/ryot/issues/1793) (still open when I wrote this) and may be related to [#1826](https://github.com/IgnisDa/ryot/issues/1826). If Ryot fixes it upstream, you won't need this and can remove it.

## What it does

The relay sits between Plex and Ryot. It keeps only the JSON `payload` part of each webhook and forwards it, otherwise unchanged, to your real Plex Sink URL.

```
Plex  ->  ryot-plex-relay  ->  Ryot  /_i/<integration id>
```

With the image gone, Ryot accepts the `media.play` request, but in my tests it then fails to process it (see [Known limits](#known-limits)). Stripping the image alone did not make Ryot complete a watch. What did was sending `media.scrobble` to Ryot twice, which is what the `SCROBBLE_REPEATS` setting does. This is a workaround for a Ryot problem I reported upstream ([#1826](https://github.com/IgnisDa/ryot/issues/1826)), not a proper fix.

## Tested with

Only my own setup, so treat anything else as untested:

- Ryot v10.5.5 (Docker, self-hosted; version as shown in the Ryot footer)
- Plex Media Server 1.43.5, with Plex Web (Chrome) as the player
- With one `media.scrobble` per watch (the default here), Ryot created the watch at 0% in progress and never completed it. In my runs where Plex also delivered each event to Ryot a second time, the episodes ended at 100%.

## Setup

1. **Ryot:** create a **Plex Sink** integration (Settings > Integrations). Enter your Plex account name exactly as Plex reports it. Open the integration's details (the eye icon) and copy its URL, which ends in `/_i/<id>`.
2. **Run the relay** (Docker Compose shown; any container runtime works). `FORWARD_URL` must be an address *the relay's container* can reach, so it may differ from the public URL Ryot shows:

   ```yaml
   services:
     ryot-plex-relay:
       image: ghcr.io/robgilm/ryot-plex-relay:latest
       restart: unless-stopped
       environment:
         # Ryot's Plex Sink URL, as reachable from this container
         - FORWARD_URL=http://ryot:8000/_i/YOUR_INTEGRATION_ID
       ports:
         - "9876:8080"
   ```

   If the image can't be pulled, build it yourself: `docker build -t ryot-plex-relay .`
3. **Plex:** open Settings > Webhooks > Add webhook and enter `http://<relay-host>:9876/plex`. **Remove any webhook that still points directly at Ryot**, or every event arrives twice and the direct copy of each play event is rejected.

Plex has historically required Plex Pass for webhooks, so check your account has it.

### Check that it works

Play something in Plex, then look at the relay's log:

```
$ docker logs ryot-plex-relay
2026-10-26 11:50:45 media.play -> Ryot 202
2026-10-26 11:51:56 media.scrobble -> Ryot 202
```

`202` only means Ryot queued the event. It processes it in the background and can still reject it, so a `202` is not proof the watch was recorded. To see what Ryot did with each event, run it with `RUST_LOG=ryot=debug` and read its log.

| Log line | Meaning |
|---|---|
| `-> Ryot 202` | Queued (not necessarily recorded) |
| `-> Ryot 400` / `404` | Check `FORWARD_URL`: wrong path or integration id |
| `-> Ryot URLError` (or another exception name) | The relay can't reach Ryot at `FORWARD_URL` |
| Nothing at all | Plex isn't reaching the relay: check the webhook URL, the port and your firewall |

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `FORWARD_URL` | required | Ryot's Plex Sink URL |
| `LISTEN_PORT` | `8080` | Port inside the container |
| `FORWARD_TIMEOUT` | `15` | Seconds to wait for Ryot |
| `SCROBBLE_REPEATS` | `1` | Times to forward each `media.scrobble` to Ryot. Set to `2` to work around watches staying at 0% (see [Known limits](#known-limits)). Other events are always sent once. |

The log has one line per event. It never logs the forward URL or the webhook payload.

## Security

- The relay has **no authentication**. Keep it on your own network and don't expose its port to the internet.
- The integration id in `FORWARD_URL` works like a password for your Plex Sink. Keep it in the environment and out of any compose file you share.
- The relay only forwards to the one URL you configure. It stores nothing.

## Known limits

- **A single `media.scrobble` does not complete a watch in Ryot** in my tests: Ryot created the watch at 0% in progress and stopped. When the same scrobble reached Ryot twice, the second one completed it. `SCROBBLE_REPEATS=2` forwards it twice. It is a workaround based on a few runs on my setup, and if Ryot fixes the problem you should set it back to `1`. In one run, a watch left stuck at 0% also stopped a new watch of another episode of the same show from being recorded.
- **Plex's `media.play` and `media.stop` often carry no playback position**, and Ryot's log shows it rejecting those events (`Webhook processing failed: No position associated with this media`). This relay can't change that. Only the `media.scrobble` event produced a watch in my tests.
- In my observation Plex sends **no webhook when you manually mark something watched**, so those never reach Ryot. This relay can't change that.
- In one of my sessions, `media.pause` events repeated an older playback position while `media.resume` reported the real one, so progress could dip while paused. I haven't checked how common that is.
- This only works around the rejected image and (optionally) the missing completion. It doesn't fix other Ryot issues.

## Sample payloads

[`docs/plex-webhook-samples.json`](docs/plex-webhook-samples.json) has Plex's webhook payloads for one episode (play, pause, resume, scrobble, stop) with account, server and player details replaced. It shows which events carry the image and which have no `viewOffset`.

## Tests

```
python -m unittest discover -s tests -v
```

The tests cover stripping the image part, JSON pass-through and an end-to-end run against a stand-in server that rejects non-UTF-8 bodies, as Ryot does.

## Support and contributions

This is a small tool I built for my own setup and shared in case it helps someone else. It is provided as-is.

- **Forking is encouraged.** It's MIT licensed, so fork it and change it however you like.
- **I'm not taking pull requests or feature requests.**
- **If it breaks** with a current version of Ryot or Plex, you can open an issue. Include your Ryot and Plex versions and the relay's log lines, and remove your account name, IP addresses and titles first. I'll look when I can, but I can't promise support.

If Ryot fixes the underlying problem upstream, this relay is no longer needed.

## License

[MIT](LICENSE)
