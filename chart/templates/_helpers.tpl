{{/*
Validation lives here rather than in a CI script alone, so a bad entry fails at
`helm template` — which means it fails in ArgoCD too, not only in a lint job
somebody can skip.
*/}}
{{- define "ns.validate" -}}
{{- if not .Values.namespace }}{{ fail "namespace is required" }}{{ end }}
{{- $classes := list "platform" "product" "saas" "sandbox" }}
{{- if not (has .Values.identity.class $classes) }}
  {{- fail (printf "identity.class %q must be one of %v" .Values.identity.class $classes) }}
{{- end }}
{{- $segments := list "edge" "platform" "app" "data" }}
{{- if not (has .Values.identity.segment $segments) }}
  {{- fail (printf "identity.segment %q must be one of %v — it selects the CiliumNetworkPolicy, and an endpoint no policy selects is UNRESTRICTED" .Values.identity.segment $segments) }}
{{- end }}
{{- if not .Values.identity.team }}{{ fail "identity.team is required" }}{{ end }}
{{- if not .Values.identity.customer }}
  {{- fail "identity.customer is required — use `internal` or `pooled` rather than leaving it empty, so that ABSENT keeps meaning forgotten" }}
{{- end }}
{{- $pss := list "restricted" "baseline" "privileged" }}
{{- if not (has .Values.guardrails.podSecurity $pss) }}
  {{- fail (printf "guardrails.podSecurity %q must be one of %v" .Values.guardrails.podSecurity $pss) }}
{{- end }}
{{- if and .Values.identity.productLine (ne .Values.identity.class "saas") }}
  {{- fail (printf "identity.productLine is set on a %q namespace. A product line is a SaaS sellable unit; on any other class the value would be the same on every namespace." .Values.identity.class) }}
{{- end }}
{{- if and (eq .Values.identity.class "saas") (not .Values.identity.productLine) }}
  {{- fail "identity.productLine is required on a saas namespace — use `shared` if it genuinely serves more than one line" }}
{{- end }}
{{- if and .Values.guardrails.quota (ne .Values.guardrails.quota "none") }}
  {{- if not (hasKey .Values.quotas .Values.guardrails.quota) }}
    {{- fail (printf "guardrails.quota %q is not a tier: %v" .Values.guardrails.quota (keys .Values.quotas)) }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "ns.labels" -}}
team: {{ .Values.identity.team | quote }}
platform.aj/class: {{ .Values.identity.class | quote }}
platform.aj/customer: {{ .Values.identity.customer | quote }}
platform.aj/segment: {{ .Values.identity.segment | quote }}
{{- if .Values.identity.productLine }}
platform.aj/product-line: {{ .Values.identity.productLine | quote }}
{{- end }}
app.kubernetes.io/managed-by: argocd
managed-by: argocd
pod-security.kubernetes.io/enforce: {{ .Values.guardrails.podSecurity | quote }}
pod-security.kubernetes.io/enforce-version: latest
pod-security.kubernetes.io/audit: restricted
pod-security.kubernetes.io/warn: restricted
{{- end -}}
