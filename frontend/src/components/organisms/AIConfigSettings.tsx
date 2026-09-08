"use client";

import { useEffect, useState } from "react";
import { Bot, CheckCircle2, Eye, EyeOff, Loader2, RotateCcw, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Badge, Button, Card } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import {
  useAIConfig,
  useResetAIConfig,
  useTestAIConfig,
  useUpdateAIConfig,
  type AIProvider,
} from "@/services/ai.service";

const PROVIDERS: { id: AIProvider; label: string; needsKey: boolean; defaultModel: string; modelHint: string }[] = [
  { id: "openai", label: "OpenAI", needsKey: true, defaultModel: "gpt-4o-mini", modelHint: "e.g. gpt-4o-mini, gpt-4o" },
  { id: "anthropic", label: "Anthropic Claude", needsKey: true, defaultModel: "claude-sonnet-5", modelHint: "e.g. claude-sonnet-5" },
  { id: "google", label: "Google Gemini", needsKey: true, defaultModel: "gemini-2.0-flash", modelHint: "e.g. gemini-2.0-flash" },
  { id: "ollama", label: "Ollama (self-hosted)", needsKey: false, defaultModel: "llama3.1", modelHint: "e.g. llama3.1, qwen2.5" },
];

function inputClass() {
  return "h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] disabled:opacity-50";
}

function Field({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="py-3 border-b border-[hsl(var(--border))] last:border-0">
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      {description && <p className="mb-2 text-xs text-[hsl(var(--foreground-muted))]">{description}</p>}
      {children}
    </div>
  );
}

export function AIConfigSettings() {
  const { hasPermission } = useAuthStore();
  const canManage = hasPermission("settings.manage");

  const { data: config, isLoading, isError } = useAIConfig();
  const updateMutation = useUpdateAIConfig();
  const resetMutation = useResetAIConfig();
  const testMutation = useTestAIConfig();

  const [provider, setProvider] = useState<AIProvider>("openai");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showKey, setShowKey] = useState(false);

  // Seed the form from the server once it loads. Deliberately not a
  // controlled reflection of `config` on every render — the person is
  // editing local draft state, and refetches (e.g. after Save) shouldn't
  // stomp on an in-progress edit in another field.
  useEffect(() => {
    if (!config) return;
    setProvider(config.provider);
    setModel(config.model);
    setBaseUrl(config.base_url ?? "");
  }, [config]);

  // PROVIDERS is a non-empty compile-time constant, so PROVIDERS[0] is
  // always defined — the `!` just satisfies noUncheckedIndexedAccess.
  const meta = PROVIDERS.find((p) => p.id === provider) ?? PROVIDERS[0]!;

  function handleProviderChange(next: AIProvider) {
    setProvider(next);
    const nextMeta = PROVIDERS.find((p) => p.id === next);
    // Switching provider: if the model field still holds the old
    // provider's default (or is empty), swap in the new provider's
    // default so the form never submits a model name that belongs to a
    // different provider.
    const isStillDefault = !model || PROVIDERS.some((p) => p.defaultModel === model);
    if (isStillDefault && nextMeta) setModel(nextMeta.defaultModel);
    setApiKey("");
  }

  function handleSave() {
    if (!model.trim()) {
      toast.error("Model name is required");
      return;
    }
    updateMutation.mutate(
      {
        provider,
        model: model.trim(),
        api_key: apiKey.trim() || undefined,
        base_url: provider === "ollama" ? (baseUrl.trim() || undefined) : undefined,
      },
      {
        onSuccess: () => {
          toast.success("AI Assistant configuration saved");
          setApiKey("");
        },
        onError: () => toast.error("Failed to save AI configuration"),
      },
    );
  }

  function handleTest() {
    testMutation.mutate(
      {
        provider,
        model: model.trim(),
        api_key: apiKey.trim() || undefined,
        base_url: provider === "ollama" ? (baseUrl.trim() || undefined) : undefined,
      },
      {
        onSuccess: (result) => {
          if (result.ok) toast.success(`Connection succeeded — ${result.message}`);
          else toast.error(`Connection failed — ${result.message}`);
        },
        onError: () => toast.error("Could not reach the test endpoint"),
      },
    );
  }

  function handleReset() {
    resetMutation.mutate(undefined, {
      onSuccess: () => {
        toast.success("Reset to the platform default configuration");
        setApiKey("");
      },
      onError: () => toast.error("Failed to reset AI configuration"),
    });
  }

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-center justify-center py-12">
          <Loader2 size={20} className="animate-spin text-[hsl(var(--foreground-muted))]" />
        </div>
      </Card>
    );
  }

  if (isError || !config) {
    return (
      <Card>
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <p className="text-sm text-[hsl(var(--foreground-muted))]">
            Couldn&apos;t load the AI Assistant configuration.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card padding={false}>
      <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-purple-600">
            <Bot size={14} className="text-white" />
          </div>
          <div>
            <h3 className="font-heading text-sm font-semibold">AI Configuration</h3>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">
              Choose which AI provider and account powers the AI Assistant for this organization.
            </p>
          </div>
        </div>
        {config.using_platform_default ? (
          <Badge>Using platform default</Badge>
        ) : (
          <Badge>Custom configuration</Badge>
        )}
      </div>

      <div className="px-5">
        {!canManage && (
          <p className="mt-3 rounded-md bg-[hsl(var(--secondary))] px-3 py-2 text-xs text-[hsl(var(--foreground-muted))]">
            You have read-only access. Ask an admin with &quot;Manage Organization Settings&quot; permission to make changes.
          </p>
        )}

        <Field label="Provider" description="Which AI service the assistant talks to.">
          <select
            value={provider}
            disabled={!canManage}
            onChange={(e) => handleProviderChange(e.target.value as AIProvider)}
            className={inputClass()}
          >
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </Field>

        <Field label="Model" description={meta.modelHint}>
          <input
            value={model}
            disabled={!canManage}
            onChange={(e) => setModel(e.target.value)}
            placeholder={meta.defaultModel}
            className={inputClass()}
          />
        </Field>

        {meta.needsKey && (
          <Field
            label="API Key"
            description={
              config.has_api_key && !config.using_platform_default
                ? `Currently saved: ${config.api_key_preview}. Enter a new key only to replace it.`
                : "This key is encrypted at rest and never shown again after saving."
            }
          >
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                disabled={!canManage}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={config.has_api_key ? "••••••••••••••••" : "Paste your API key"}
                className={inputClass() + " pr-9"}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
                tabIndex={-1}
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </Field>
        )}

        {provider === "ollama" && (
          <Field label="Ollama Server URL" description="Where your self-hosted Ollama instance is reachable.">
            <input
              value={baseUrl}
              disabled={!canManage}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://localhost:11434"
              className={inputClass()}
            />
          </Field>
        )}

        {testMutation.data && (
          <div
            className={`mt-1 flex items-start gap-2 rounded-md px-3 py-2 text-xs ${
              testMutation.data.ok
                ? "bg-green-500/10 text-green-600 dark:text-green-400"
                : "bg-red-500/10 text-red-600 dark:text-red-400"
            }`}
          >
            {testMutation.data.ok ? <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> : <XCircle size={14} className="mt-0.5 shrink-0" />}
            <span className="break-words">{testMutation.data.message}</span>
          </div>
        )}
      </div>

      {canManage && (
        <div className="flex items-center justify-between border-t border-[hsl(var(--border))] px-5 py-4">
          <Button
            variant="ghost"
            size="sm"
            icon={<RotateCcw size={13} />}
            onClick={handleReset}
            disabled={resetMutation.isPending || config.using_platform_default}
          >
            Reset to default
          </Button>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleTest}
              disabled={testMutation.isPending || (meta.needsKey && !apiKey.trim() && !config.has_api_key)}
            >
              {testMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : "Test connection"}
            </Button>
            <Button size="sm" onClick={handleSave} disabled={updateMutation.isPending}>
              {updateMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : "Save changes"}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}