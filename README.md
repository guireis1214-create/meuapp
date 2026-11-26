# MenuFlow — protótipo multi-restaurante

## Deploy no Render
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Root Directory: `menuflow_render_fix` (if uploading this folder as a subfolder), or the repository root if its contents are placed there.

## Fluxos incluídos
- Cadastro e login de clientes, com senha individual e hash PBKDF2.
- Solicitação de cadastro de restaurante, login individual e aprovação do suporte.
- Dados de cardápio, pedidos e status com escopo do restaurante autenticado.
- Cliente escolhe restaurante, itens, quantidades, extras, ingredientes a remover, observações, endereço e pagamento.
- Restaurante vê e atualiza somente os pedidos vinculados a seu ID.

## Conta inicial de suporte
- E-mail padrão: `support@menuflow.local`
- Senha padrão: `ChangeMe-2026!`
- Configure `MENUFLOW_SUPPORT_EMAIL` e `MENUFLOW_SUPPORT_PASSWORD` como variáveis de ambiente antes de publicar.
- Troque o segredo padrão antes de colocar em uso real. Não use dados reais nesse protótipo.

## Limitações
Este é um protótipo para testes, ainda não uma plataforma pronta para operação comercial. Antes de produção: usar HTTPS, alterar senha inicial, revisar permissões e validação, adicionar recuperação de senha, antifraude, proteção contra CSRF conforme arquitetura, rate limiting, backup e migrações, regras de entrega/ pagamento, política de privacidade, e testes de segurança. Tokens de sessão expiram em 7 dias. SQLite pode não ser adequado para operação em escala.
