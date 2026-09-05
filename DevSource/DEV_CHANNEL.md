# CS2py development channel

`CS2pyDev.exe` keeps its separate checkout in:

```text
Documents\CS2pyDev
```

The launcher refreshes only this `DevSource` tree from the repository. Runtime
files such as `settings.json`, `.requirements_sha`, logs, and local tokens are
created locally and are not part of the DevSource checkout.

To use the optional skin-share relay, configure the local `settings.json` with
the relay URL and shared token. Do not commit that file or any token.
