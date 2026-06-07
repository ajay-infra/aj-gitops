{{- define "rollout-template.fullname" -}}
{{- .Values.app | default .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "rollout-template.labels" -}}
app.kubernetes.io/name:       {{ .Values.app | default .Release.Name | quote }}
app.kubernetes.io/component:  {{ .Values.component | quote }}
app.kubernetes.io/version:    {{ .Values.version | quote }}
app.kubernetes.io/managed-by: argocd
team:  {{ required "team is required" .Values.team | quote }}
env:   {{ .Values.env | quote }}
model: {{ .Values.model | default "internal" | quote }}
{{- end }}

{{- define "rollout-template.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.app | default .Release.Name | quote }}
team: {{ .Values.team | quote }}
{{- end }}
