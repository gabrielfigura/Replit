# CLEVER Bot

Este é um bot Telegram que monitora resultados de uma API de jogos e envia sinais com base em padrões predefinidos. O bot foi configurado para rodar no Replit com um simples clique em "Run", com o `BOT_TOKEN` e o `CHAT_ID` embutidos diretamente no código.

**Atenção**: O `BOT_TOKEN` e o `CHAT_ID` estão embutidos no arquivo `main.py`. Para segurança, mantenha este repositório privado, pois expor o token pode permitir que terceiros controlem o bot. Considere usar variáveis de ambiente (Replit Secrets) em vez de embutir os valores diretamente.

## Como Configurar no Replit

1. **Importar o Repositório**:
   - No Replit, clique em "Create Repl" e selecione "Import from GitHub".
   - Insira a URL deste repositório.

2. **Verificar o Token e o Chat ID**:
   - O `BOT_TOKEN` e o `CHAT_ID` estão embutidos em `main.py`. Certifique-se de que são válidos:
     - `BOT_TOKEN`: Deve ser um token ativo obtido via BotFather no Telegram.
     - `CHAT_ID`: Deve ser o ID correto do grupo ou canal onde o bot enviará mensagens.
   - Se necessário, edite `main.py` para substituir esses valores pelos seus.

3. **Executar o Bot**:
   - Clique no botão "Run" no Replit.
   - O Replit instalará automaticamente as dependências listadas em `requirements.txt` e executará o script `main.py`.

4. **Monitoramento**:
   - Verifique o console do Replit para logs de depuração.
   - Certifique-se de que a API (`https://api.casinoscores.com`) está acessível e que o bot está enviando mensagens ao Telegram.

## Notas
- **Segurança**: Como o `BOT_TOKEN` está embutido no código, evite compartilhar o repositório publicamente. Considere usar a seção "Secrets" do Replit para maior segurança.
- **Plano Gratuito do Replit**: O bot pode ser interrompido após um período de inatividade. Considere um plano pago ou use um serviço como UptimeRobot para manter o projeto ativo.
- **Limites de Requisições**: Monitore os limites de requisições da API e do Telegram para evitar bloqueios.
- **Depuração**: Logs detalhados são exibidos no console do Replit. Use-os para identificar problemas, como falhas na API ou no Telegram.

## Dependências
As dependências estão listadas em `requirements.txt` e serão instaladas automaticamente:
- `aiohttp`: Para chamadas HTTP à API.
- `python-telegram-bot`: Para interação com o Telegram.
- `tenacity`: Para retries em caso de falhas.

Se precisar de ajuda, consulte os logs no console ou entre em contato com o desenvolvedor.
