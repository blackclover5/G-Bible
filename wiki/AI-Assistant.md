# AI Assistant

The Assistant is optional and does not exist in a fresh install. Open **Settings → AI Assistant** to enable it, then choose a provider. G-Bible downloads no model: a local server (Ollama, LM Studio, llama.cpp) or a cloud key supplies the answers. Once enabled it can retrieve passages from installed resources, show citations, and support actions such as Explain, Summarise, Translate, Smart Search, topic questions, and sermon research. Treat its output as research assistance and verify claims against cited sources. The same page can disable the Assistant again.

## Configure a provider

Enable it in **Settings → AI Assistant**, choose a provider, enter your own key if required, select a model, and use **Test** to check connectivity and discover available models. Local providers such as Ollama, LM Studio, and llama.cpp can keep requests on your computer. Cloud providers require network access and may charge or enforce usage limits.

Provider support and capabilities vary by release. The settings page is the current source for provider availability, connection status, and usage information.

## What is sent

For a cloud provider, G-Bible can send your question, retrieved passages, and recent conversation context. Depending on the selected options, it may also send relevant notes, highlights, clippings, or topic-guide content. Query expansion and the optional answer reviewer may make additional requests to the provider you chose. The full library is not uploaded. No request is made to a provider you have not configured.

With a local provider, requests stay on the machine only if the provider endpoint is genuinely local. Do not enable use of personal notes with a cloud provider unless you are comfortable sharing those notes with that provider.

API keys are stored outside `gbible.db` in a credential file beside the database. Keep your data directory private.

## Citations and limits

The Assistant retrieves source material from your installed library, then asks the model to reason over it. It can resolve named people and events to likely passages, and search again when the first sources are thin. Click citations to inspect the underlying source. A citation is a path to verification, not proof that the model interpreted a source correctly. The model cannot cite books that are not installed or passages it did not retrieve.

Sermon research provides sourced notes and preparation material; it is designed not to draft a finished sermon. Conversations and usage records are stored locally. Read the in-app privacy note before selecting a cloud provider.

## Troubleshooting

- **Provider unavailable:** check that the local server is running, or that the cloud key and network are correct; press **Test**.
- **No useful sources:** install relevant resources, narrow the library scope, or ask a more specific question.
- **Unexpected bill or quota limit:** review Settings → AI usage and select a lower-cost/local provider.
- **Privacy concern:** turn off use of personal material or switch to a local provider before asking.

For implementation details, see the [AI specification](../docs/ai.md).
