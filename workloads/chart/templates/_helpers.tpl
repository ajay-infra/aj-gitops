{{/*
Validation lives here rather than in a CI script alone, so a bad entry fails at
`helm template` — which means it fails in ArgoCD too, not only in a lint job
somebody can skip.
*/}}
{{- define "ns.validate" -}}
{{- if not .Values.namespace }}{{ fail "namespace is required — it is the last path segment" }}{{ end }}
{{- if not .Values.cluster }}{{ fail "cluster is required — it is the third path segment" }}{{ end }}
{{- $classes := list "platform" "product" "saas" "sandbox" }}
{{- if not (has .Values.class $classes) }}
  {{- fail (printf "class %q must be one of %v" .Values.class $classes) }}
{{- end }}
{{- $segments := list "edge" "platform" "app" "data" }}
{{- if not (has .Values.segment $segments) }}
  {{- fail (printf "segment %q must be one of %v — it selects the CiliumNetworkPolicy, and an endpoint no policy selects is UNRESTRICTED" .Values.segment $segments) }}
{{- end }}
{{- if not .Values.team }}{{ fail "team is required" }}{{ end }}
{{- if not .Values.customer }}
  {{- fail "customer is required — use `internal` or `pooled` rather than leaving it empty, so that ABSENT keeps meaning forgotten" }}
{{- end }}
{{- $pss := list "restricted" "baseline" "privileged" }}
{{- if not (has .Values.podSecurity $pss) }}
  {{- fail (printf "podSecurity %q must be one of %v" .Values.podSecurity $pss) }}
{{- end }}
{{- if and .Values.productLine (ne .Values.class "saas") }}
  {{- fail (printf "productLine is set on a %q namespace. A product line is a SaaS sellable unit; on any other class the value would be the same on every namespace." .Values.class) }}
{{- end }}
{{- if and (eq .Values.class "saas") (not .Values.productLine) }}
  {{- fail "productLine is required on a saas namespace — use `shared` if it genuinely serves more than one line" }}
{{- end }}
{{- if and .Values.quota (ne .Values.quota "none") }}
  {{- if not (hasKey .Values.quotas .Values.quota) }}
    {{- fail (printf "quota %q is not a tier: %v" .Values.quota (keys .Values.quotas)) }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "ns.labels" -}}
team: {{ .Values.team | quote }}
platform.aj/class: {{ .Values.class | quote }}
platform.aj/customer: {{ .Values.customer | quote }}
platform.aj/segment: {{ .Values.segment | quote }}
{{- if .Values.productLine }}
platform.aj/product-line: {{ .Values.productLine | quote }}
{{- end }}
app.kubernetes.io/managed-by: argocd
managed-by: argocd
pod-security.kubernetes.io/enforce: {{ .Values.podSecurity | quote }}
pod-security.kubernetes.io/enforce-version: latest
pod-security.kubernetes.io/audit: restricted
pod-security.kubernetes.io/warn: restricted
{{- end -}}
