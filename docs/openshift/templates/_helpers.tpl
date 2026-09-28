{{/*
Login name from users: list. Prefers the first entry with sshKey, else the first entry.
Usage: include "teuthology.loginName" .Values.teuthology.users
*/}}
{{- define "teuthology.loginName" -}}
{{- $picked := false -}}
{{- $name := "teuthology" -}}
{{- range . | default list -}}
{{- if and (not $picked) .sshKey -}}
{{- $name = .sshUser | default .name | default "teuthology" -}}
{{- $picked = true -}}
{{- end -}}
{{- end -}}
{{- if not $picked -}}
{{- range . | default list -}}
{{- if not $picked -}}
{{- $name = .sshUser | default .name | default "teuthology" -}}
{{- $picked = true -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $name -}}
{{- end -}}

{{/*
Password for the same primary user as teuthology.loginName.
Usage: include "teuthology.loginPassword" .Values.teuthology.users
*/}}
{{- define "teuthology.loginPassword" -}}
{{- $picked := false -}}
{{- $password := "passwd" -}}
{{- range . | default list -}}
{{- if and (not $picked) .sshKey -}}
{{- $password = .password | default "passwd" -}}
{{- $picked = true -}}
{{- end -}}
{{- end -}}
{{- if not $picked -}}
{{- range . | default list -}}
{{- if not $picked -}}
{{- $password = .password | default "passwd" -}}
{{- $picked = true -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $password -}}
{{- end -}}

{{/*
Literal authorizedKeys lines from a users: list (all users, deduped).
Usage: include "teuthology.usersAuthorizedKeys" .Values.teuthology.users
*/}}
{{- define "teuthology.usersAuthorizedKeys" -}}
{{- $seen := dict -}}
{{- range . | default list -}}
{{- range .authorizedKeys | default list -}}
{{- if and . (not (hasKey $seen .)) -}}
{{- $_ := set $seen . true -}}
{{ . }}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Lab keypair public keys from users[].sshKey.publicKey (deduped).
Usage: include "teuthology.usersLabPublicKeys" .Values.teuthology.users
*/}}
{{- define "teuthology.usersLabPublicKeys" -}}
{{- $seen := dict -}}
{{- range . | default list -}}
{{- $pub := dig "sshKey" "publicKey" "" . -}}
{{- if and $pub (not (hasKey $seen $pub)) -}}
{{- $_ := set $seen $pub true -}}
{{ $pub }}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
First lab private key from users[].sshKey.privateKey.
Usage: include "teuthology.usersLabPrivateKey" .Values.teuthology.users
*/}}
{{- define "teuthology.usersLabPrivateKey" -}}
{{- $out := "" -}}
{{- range . | default list -}}
{{- if not $out -}}
{{- $out = dig "sshKey" "privateKey" "" . -}}
{{- end -}}
{{- end -}}
{{- $out -}}
{{- end -}}

{{/*
First lab public key from users[].sshKey.publicKey.
Usage: include "teuthology.usersLabPublicKeyPrimary" .Values.teuthology.users
*/}}
{{- define "teuthology.usersLabPublicKeyPrimary" -}}
{{- $out := "" -}}
{{- range . | default list -}}
{{- if not $out -}}
{{- $out = dig "sshKey" "publicKey" "" . -}}
{{- end -}}
{{- end -}}
{{- $out -}}
{{- end -}}
