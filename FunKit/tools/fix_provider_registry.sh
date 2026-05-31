# modules/provider_registry.py  (replace these two methods)

def get(self, key: Optional[str]):
    # If no providers loaded, reload
    if not self.providers:
        self._load()

    # Exact key wins
    if key and key in self.providers:
        return self.providers[key]

    # Default key if present
    if self.default_key in self.providers:
        return self.providers[self.default_key]

    # Fallback: first provider if any
    if self.providers:
        return next(iter(self.providers.values()))

    # Last resort: raise a clear error
    raise RuntimeError("No providers configured. Check storage/providers.json")

def read_selected(self) -> str:
    try:
        with open(APP_STATE_PATH, "r", encoding="utf-8") as f:
            k = json.load(f).get("selected_provider")
            if k and k in self.providers:
                return k
    except Exception:
        pass
    # fallbacks if file missing or invalid
    if self.default_key in self.providers:
        return self.default_key
    if self.providers:
        return next(iter(self.providers.keys()))
    return "openai"  # harmless placeholder; won't be used if providers empty

