# Manifesto de Atualização e SHA-256 (Fase 11)

## Objetivo

Definir exatamente qual arquivo representa uma release Desktop e como o
cliente comprova que o artefato baixado é byte a byte o mesmo autorizado
para aquela versão -- um schema tipado e versionado (`manifest.json`) mais a
cadeia completa de verificação (tamanho + SHA-256) entre o download e a
entrega ao Updater da Fase 10.

## Inventário encontrado

- **`scripts/create_release_files.py`** já gera um `latest.json` (formato
  ad-hoc, sem `manifest_schema_version`, sem objeto `artifact` estruturado,
  campos como `min_supported_version`/`tag`/`installer` diferentes do pedido
  desta fase) + um arquivo `.sha256` a partir do instalador Inno Setup em
  `release/ControleProducaoSetup-{version}.exe`. **Preservado sem
  alteração** -- ainda é consumido pelo mecanismo legado
  (`update_checker.py`/`update_downloader.py`, ambos da Fase 10). O novo
  `manifest.json` (`scripts/generate_release_manifest.py`) é um artefato
  **paralelo e adicional**, seguindo o schema exigido por esta fase; os dois
  convivem sem conflito, exatamente como o Updater novo (Fase 10) convive
  com o mecanismo de atualização antigo.
- **`app/services/update_checker.py`** já consulta a API de Releases do
  GitHub (`RELEASES_API_URL`, hardcoded) e tem seu **próprio** parser de
  SemVer informal (`VersionInfo`/`parse_version`/`is_newer_version`),
  duplicado do `app.versioning` da Fase 01. Não alterado nesta fase (fora de
  escopo); o novo código desta fase reaproveita `app.versioning.parser`
  corretamente, sem repetir essa duplicação.
- **`app/services/update_downloader.py`** já tinha `sha256_file()` por
  streaming (chunks de 1MB) -- o mesmo padrão já existia em
  `app/updater/validation.py` (Fase 10) e em `scripts/create_release_files.py`.
  **Reaproveitado diretamente** de `app.updater.validation.sha256_file`
  (Fase 10) em vez de duplicado uma quarta vez.
- **Rotina de staging da Fase 10**: `app/updater/downloader.py` (download
  streaming, `.part`, retry) e `app/updater/orchestrator.py`
  (`UpdaterOrchestrator.run_update`, que já valida o pacote via
  `verify_package`/`PackageValidationStatus` antes de extrair). O gate desta
  fase (`app/updater/manifest_gate.py`) opera **antes** desse fluxo: baixa e
  verifica o artefato pelo manifesto, e só então constrói um `UpdateRequest`
  já com `package_expected_hash`/`package_expected_size` preenchidos --
  nunca modifica o orquestrador da Fase 10.
- **Nomenclatura real dos instaladores**: `ControleProducaoSetup-{version}.exe`
  (`installer/ControleProducao.iss`, `scripts/create_release_files.py`).
- **Ferramenta de build**: PyInstaller (`ControleProducao.spec`,
  `Updater.spec`) + Inno Setup, saída em `dist/`/`release/`.
- **Checksum já existente**: só SHA-256 (`sha256_file`, duas implementações
  independentes antes desta fase); nenhum MD5/SHA-1 em uso.
- **Versão/política**: `app/version.py` (`APP_VERSION`), `app/versioning/`
  (SemVer tipado, Fase 01), `app/services/compatibility_check.py` (Fase 03) --
  todos reaproveitados, nenhum duplicado.
- **GitHub Releases**: usado hoje só pelo mecanismo legado. O novo código
  desta fase (`manifest_provider.py`) não referencia GitHub em nenhum lugar
  -- a fonte é sempre um `ManifestProvider` genérico e substituível (Secao 23).

## Schema do manifesto implementado

`app/updater/manifest.py`: `ReleaseManifest` + `ArtifactDescriptor`
(dataclasses tipadas), `MANIFEST_SCHEMA_VERSION = 1`,
`SUPPORTED_MANIFEST_SCHEMA_VERSIONS = {1}`. Estrutura idêntica ao exemplo da
Seção 8 do prompt:

```json
{
  "manifest_schema_version": 1,
  "release_version": "2.6.0",
  "channel": "production",
  "published_at": "2026-08-11T12:00:00Z",
  "minimum_server_version": "0.8.0",
  "api_contract_version": "v1",
  "artifact": {
    "filename": "ControleProducaoSetup-2.6.0.exe",
    "size_bytes": 123456789,
    "sha256": "<64 hex chars>",
    "content_type": "application/vnd.microsoft.portable-executable"
  },
  "artifact_url": null,
  "release_notes": null
}
```

Schema desconhecido/futuro é **sempre rejeitado explicitamente**
(`SUPPORTED_MANIFEST_SCHEMA_VERSIONS`), nunca "adivinhado".

## Campos e regras de validação

`validate_manifest_dict()` -- fail-closed, um `ManifestValidationError` por
qualquer campo ausente/inválido, nunca um fallback silencioso:

| Campo | Regra |
|---|---|
| `manifest_schema_version` | inteiro positivo, precisa estar em `SUPPORTED_MANIFEST_SCHEMA_VERSIONS` |
| `release_version` | SemVer válido (`app.versioning.parser.parse_version`, Fase 01) |
| `channel` | `production` ou `test` (`ReleaseChannel`) |
| `published_at` | ISO-8601 com timezone (aceita sufixo `Z`), sempre convertido para UTC |
| `minimum_server_version` | SemVer válido |
| `api_contract_version` | string não vazia |
| `artifact.filename` | nome seguro (`is_safe_artifact_filename`, Seção 16) |
| `artifact.size_bytes` | inteiro > 0 |
| `artifact.sha256` | hex de 64 caracteres (normalizado para lowercase) |
| `artifact_url` | opcional; se presente, precisa ser `http://`/`https://` (nunca `file://`/`ftp://`/UNC) |
| `release_notes` | opcional; texto simples |

`is_safe_artifact_filename` testada contra todos os exemplos da Seção 16
(`../update.exe`, `..\update.exe`, `C:\temp\update.exe`,
`/server/share/update.exe`, `subdir/update.exe` -- todos rejeitados;
`Sistema-Setup-3.2.0.exe` aceito).

## Gerador do manifesto

`scripts/generate_release_manifest.py::generate_manifest(artifact_path, ...)`
(Seção 11): `stat` do tamanho + `sha256_file` (streaming) calculados **sempre
a partir do arquivo real** -- o script nunca aceita um hash informado
manualmente. `release_version` sem `--release-version` é derivada de
`app.version.APP_VERSION` (fonte central, Fase 01); se informada
explicitamente e divergente, falha (mesmo padrão de
`scripts/build_release_image.py`, Fase 07). O manifesto recém-construído é
validado (`validate_manifest_dict`) antes de ser escrito em disco --
nunca grava algo que o próprio cliente rejeitaria. Serialização
determinística via `ReleaseManifest.to_canonical_json()` (UTF-8, chaves
ordenadas, indentação fixa, `published_at` sempre UTC com sufixo `Z`, sem
caminho absoluto de máquina de build, sem secret).

## Cálculo SHA-256

Reaproveitado de `app.updater.validation.sha256_file` (Fase 10): streaming
em chunks de 1MB, nunca carrega o arquivo inteiro em memória. Testado com um
arquivo de 30MB (múltiplos chunks) confirmando que o hash bate exatamente
com `hashlib.sha256(path.read_bytes())` calculado de referência. Falha de
leitura propaga a exceção (nunca retorna hash parcial) -- capturada pela
camada de verificação e mapeada para `READ_ERROR`.

## Validação do artefato no cliente

`app/updater/artifact_verification.py`: `ArtifactVerificationStatus`
(`NOT_CHECKED`/`VALID`/`SIZE_MISMATCH`/`HASH_MISMATCH`/`MANIFEST_INVALID`/
`FILE_MISSING`/`READ_ERROR`, exatamente os 7 valores da Seção 20).
`verify_artifact_against_manifest`: tamanho conferido **antes** do hash
(Seção 18 -- tamanho divergente já rejeita sem precisar ler o arquivo
inteiro de novo para o hash); comparação de hash via `hmac.compare_digest`
(constant-time, Seção 19). `verify_download(manifest_data, file_path)` é o
ponto de entrada único: manifesto inválido nunca chega a checar o arquivo
(`MANIFEST_INVALID` primeiro).

## Integração com a Fase 10

`app/updater/manifest_gate.py` é o **único** lugar que produz um
`UpdateRequest` a partir de um manifesto -- só devolve um request quando
manifesto E artefato foram validados como `VALID`:

1. `fetch_and_validate_manifest(provider, last_known_good_store=...)` --
   busca (via `ManifestProvider` substituível, nunca GitHub hardcoded) e
   valida estruturalmente; grava no `LastKnownGoodManifestStore` (Seção 26 --
   um manifesto inválido nunca sobrescreve o último válido, usado só para
   diagnóstico) somente após validação bem-sucedida.
2. `download_and_verify_artifact(manifest, destination_dir, quarantine_dir, source=...)`
   -- reaproveita `app.updater.downloader.download_package` (Fase 10, streaming)
   sem duplicar lógica de rede; verifica o arquivo baixado contra o
   manifesto; se não `VALID`, move para quarentena (nunca apaga, nunca fica
   executável pelo fluxo normal) e levanta `ManifestGateError` -- **nenhum
   caminho leva a instalação/swap quando o artefato não é `VALID`**.
3. `build_update_request(manifest, artifact_path, ...)` -- só alcançável
   após o passo 2 ter sucesso; sempre preenche
   `package_expected_hash`/`package_expected_size` a partir do manifesto
   (nunca deixa o `UpdateRequest` cair no caminho `MISSING_METADATA` da
   verificação interna da própria Fase 10, que continua rodando como uma
   segunda camada de defesa em profundidade).

Testado ponta a ponta contra o `UpdaterOrchestrator` real da Fase 10 (sem
mocks na fronteira): manifesto válido + artefato íntegro percorre todo o
fluxo até `SUCCESS` com o executável trocado; artefato adulterado nunca
chega a gerar um `UpdateRequest`, então o Updater da Fase 10 **nunca é
sequer invocado**.

Nenhum parâmetro de linha de comando, flag de debug ou ação de UI permite
pular a verificação -- não existe nenhum "bypass" no código (Seção 21, gate
obrigatório).

### Compatibilidade antes do download

`app/updater/manifest_policy.py::evaluate_manifest_against_policy` (Seção 22)
aplica, usando as mesmas comparações de `app.versioning.parser` já usadas
pela Fase 03: servidor abaixo do mínimo -> não baixar; contrato de API
desconhecido ou divergente -> não baixar; versão já instalada -> não
reinstalar; downgrade sem `allow_downgrade=True` explícito -> recusar. **Não
substitui** a política central das Fases 01-03 (Seção 10) -- é uma checagem
adicional e opcional para evitar gastar rede/disco, nunca a decisão final de
habilitar/bloquear o uso do sistema.

### Origem do manifesto

`app/updater/manifest_provider.py`: `ManifestProvider` (protocolo),
`HttpManifestProvider` (rejeita qualquer esquema que não seja http/https já
na construção; não segue redirects -- Seção 24; envia
`Cache-Control: no-cache`/`Pragma: no-cache` -- Seção 25) e
`LocalFileManifestProvider` (somente testes/recuperação explícita, nunca
produção). Nenhuma URL do GitHub ou de qualquer provedor específico
hardcoded em nenhum desses módulos.

## Arquivos criados

`app/updater/manifest.py`, `artifact_verification.py`, `manifest_policy.py`,
`manifest_provider.py`, `manifest_store.py`, `manifest_gate.py`,
`scripts/generate_release_manifest.py`,
`docs/architecture/UPDATE_MANIFEST.md`, 8 arquivos de teste
(`tests/test_manifest_schema.py`, `test_artifact_verification.py`,
`test_manifest_policy.py`, `test_manifest_provider.py`,
`test_manifest_store.py`, `test_manifest_gate.py`,
`test_manifest_updater_integration.py`, `test_generate_release_manifest.py`).

## Arquivos alterados

`app/updater/paths.py` (dois novos helpers aditivos: `manifest_dir()`,
`quarantine_dir()` -- mesmo padrão dos diretórios já existentes da Fase 10,
nenhum comportamento anterior alterado).

## Testes criados

76 testes novos (todos com arquivos/diretórios reais via
`tempfile.TemporaryDirectory` e um `ZipFile` real para o teste de integração
com a Fase 10):
schema (27), verificação de artefato (8, incluindo corrupção/truncamento/
arquivo ausente), política pré-download (8), provedor de manifesto (10,
incluindo rejeição de esquema e resposta HTTP simulada), armazenamento do
último manifesto válido (4), gate de integração com a Fase 10 (9 + 2 de
integração real fim-a-fim), gerador CLI (8).

## Resultado da suite completa

Os **76 testes novos da Fase 11 passam 100%** isoladamente (verificado
nesta sessão). A suíte completa do repositório continua com as falhas de
trabalho concorrente já documentadas no relatório da Fase 10 (arquivos de
`api/` modificados por outra sessão em paralelo, sem qualquer relação causal
com esta fase, que é inteiramente Desktop-side) -- ver relatório da Fase 10,
item 15, para o detalhamento; a situação não mudou entre as duas fases.

## Riscos/pendências

- `artifact_url` só é usado quando explicitamente fornecido (via manifesto
  ou parâmetro `source`); a fonte oficial de distribuição continua sendo
  definida pela Fase 12.
- `HttpManifestProvider` não segue redirects propositalmente (Seção 24); se
  a infraestrutura real de distribuição depender de redirect (ex.: CDN),
  isso precisará ser revisitado com uma política explícita de esquemas
  permitidos, não simplesmente reativado sem critério.
- O manifesto legado (`latest.json`) e o novo (`manifest.json`) coexistem
  sem estarem unificados -- a decisão de aposentar o mecanismo legado
  pertence a uma fase futura (junto da distribuição real, Fase 12).

## O que ficou fora de escopo

Servidor distribuindo os artefatos (Fase 12), política visual
obrigatória/opcional (Fase 13), maintenance mode (Fase 14), canal
piloto/produção completo (Fase 15), auditoria central consolidada (Fase 16),
certificado Authenticode/assinatura de código, PKI própria para assinatura
criptográfica do manifesto.
