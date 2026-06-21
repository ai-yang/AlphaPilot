import { useCallback, useEffect, useState } from "react";
import { buildParams, defaultValuesFor, FieldSpec, FieldValue } from "./paramSpecs";

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loader());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, deps);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, error, loading, refresh, setData };
}

export function useJsonInput(initial = "{}") {
  const [raw, setRaw] = useState(initial);
  const parse = () => {
    if (!raw.trim()) return {};
    const value = JSON.parse(raw);
    if (value === null || Array.isArray(value) || typeof value !== "object") {
      throw new Error("JSON must be an object");
    }
    return value as Record<string, unknown>;
  };
  return { raw, setRaw, parse };
}

export function useParamForm(specs: FieldSpec[], advancedJson = "{}") {
  const [values, setValues] = useState<Record<string, FieldValue>>(() => defaultValuesFor(specs));
  const [errors, setErrors] = useState<Record<string, string>>({});

  const signature = specs.map((field) => `${field.key}:${String(field.defaultValue ?? "")}`).join("|");

  useEffect(() => {
    setValues(defaultValuesFor(specs));
    setErrors({});
  }, [signature]);

  function setValue(key: string, value: FieldValue) {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function parse() {
    try {
      setErrors({});
      return buildParams(specs, values, advancedJson);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setErrors({ _form: message });
      throw err;
    }
  }

  return { values, setValue, setValues, errors, parse };
}
