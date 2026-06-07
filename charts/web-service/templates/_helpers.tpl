{{/*
Full resource name — release name is the app name.
*/}}
{{- define "web-service.fullname" -}}
{{- .Values.app | default .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Standard K8s recommended labels + platform taxonomy labels.
Applied to every resource this chart creates.
*/}}
{{- define "web-service.labels" -}}
app.kubernetes.io/name:       {{ .Values.app | default .Release.Name | quote }}
app.kubernetes.io/component:  {{ .Values.component | quote }}
app.kubernetes.io/version:    {{ .Values.version | quote }}
app.kubernetes.io/managed-by: argocd
team:  {{ required "team is required" .Values.team | quote }}
env:   {{ .Values.env | quote }}
model: {{ .Values.model | default "internal" | quote }}
{{- end }}

{{/*
Selector labels — stable subset used by Service and ScaledObject target ref.
Must not change after first deploy (changing selectors requires delete+recreate).
*/}}
{{- define "web-service.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.app | default .Release.Name | quote }}
team: {{ .Values.team | quote }}
{{- end }}
