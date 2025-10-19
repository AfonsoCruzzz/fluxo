import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour
from spade.message import Message

class AgenteEnviador(Agent):
    class EnviarMensagem(PeriodicBehaviour):
        async def run(self):
            msg = Message(to="agente_receptor@localhost")
            msg.body = f"Mensagem de {self.agent.jid}"
            await self.send(msg)
            print(f"📤 {self.agent.jid} enviou: {msg.body}")

    async def setup(self):
        self.add_behaviour(self.EnviarMensagem(period=3))

class AgenteReceptor(Agent):
    class ReceberMensagem(PeriodicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=5)
            if msg:
                print(f"📥 {self.agent.jid} recebeu: {msg.body}")

    async def setup(self):
        self.add_behaviour(self.ReceberMensagem(period=1))

async def main():
    print("🚀 Iniciando agentes com Prosody...")
    
    # Criar agentes
    enviador = AgenteEnviador("agente_enviador@localhost", "senha")
    receptor = AgenteReceptor("agente_receptor@localhost", "senha")
    
    # Iniciar agentes
    await enviador.start()
    await receptor.start()
    
    print("✅ Agentes iniciados. Pressione Ctrl+C para parar.")
    
    try:
        # Manter rodando
        await asyncio.Future()
    except KeyboardInterrupt:
        print("🛑 Parando agentes...")
        await enviador.stop()
        await receptor.stop()

if __name__ == "__main__":
    spade.run(main())