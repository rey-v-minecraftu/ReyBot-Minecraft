import discord
from discord.ext import commands
import random
import sys 
import os 
import threading 
from flask import Flask 
import unicodedata 

# ===============================================
# A) NASTAVENÍ BOTA
# ===============================================

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 

bot = commands.Bot(command_prefix='!', intents=intents)

# ===============================================
# B) GLOBÁLNÍ DATA A TŘÍDY
# ===============================================

# Globalni konstanty
RUDY_POKLDADU = ["Netherit", "Zlato", "Diamant", "Železo", "Uhlí"] # Dostupné rudy, které mohou padnout
dostupne_postavy_stav = {} # Sleduje dostupné postavy pro kanál při výběru

# --- Globální slovníky pro sledování stavu ---
aktivni_hry = {} 
vyber_postavy = {}

class Karta:
    """Základní definice karty pro všechny typy (Poklad, Příšera, Akce)"""
    def __init__(self, nazev, typ, rarita=None, utok=0, zivoty=0, odmena_reycoiny=0, efekt_text=None, image_url=None):
        self.nazev = nazev
        self.typ = typ  # 'Poklad', 'Prisera', 'Akce', 'Postava'
        self.rarita = rarita # Zde držíme typ rudy (např. 'Netherit') pro aktivaci
        self.utok = utok
        self.zivoty = zivoty
        self.odmena_reycoiny = odmena_reycoiny
        self.efekt_text = efekt_text 
        self.image_url = image_url

    def get_embed_data(self):
        """Vrátí data pro zobrazení karty v Discord Embedu"""
        barva = {
            'Netherit': 0xff0000, 'Zlato': 0xffa500, 'Diamant': 0x00ffff, 
            'Železo': 0xaaaaaa, 'Prisera': 0x8b0000, 'Akce': 0x00ff00,
            'Ruda': 0x4a4a4a, 'Postava': 0x800080, 'Uhlí': 0x222222,
            'Poklad': 0x694200 
        }.get(self.rarita or self.typ, 0x000000)
        
        popis = f"Typ: {self.typ}"
        if self.rarita:
            popis += f" | Ruda: {self.rarita}" 
        if self.utok > 0 or self.zivoty > 0:
             popis += f"\n⚔️ Útok: {self.utok} | ❤️ Životy: {self.zivoty}"
        if self.efekt_text:
            popis += f"\nPopis: {self.efekt_text}"
            
        embed_data = {'title': self.nazev, 'description': popis, 'color': barva}
        if self.image_url:
            embed_data['image_url'] = self.image_url
        return embed_data


# --- DEFINICE POSTAV ---
POSTAVY = {
    "rey_koranteng": Karta("Rey Koranteng", "Postava", "Netherit", efekt_text="Zvyšuje útok o +3"),
    "lucie_borhyova": Karta("Lucie Borhyová", "Postava", "Zlato", efekt_text="Vyléčí 3 životy (max 10 HP)"),
    "ondra_sokol": Karta("Ondra Sokol", "Postava", "Diamant", efekt_text="Vezme 2 karty z ruky/vyložených karet"),
    "ales_hama": Karta("Aleš Háma", "Postava", "Železo", efekt_text="Blokuje 1 útok s hodnotou 3 dmg na sebe"),
}


class Hrac:
    """Sledování stavu hráče (Discord ID, životy, karty)"""
    
    RUDY_POSTAV = {
        "rey_koranteng": "Netherit",
        "lucie_borhyova": "Zlato",
        "ondra_sokol": "Diamant",
        "ales_hama": "Železo",
    }
    
    def __init__(self, discord_id, postava_karta):
        self.id = discord_id
        self.postava = postava_karta        
        self.zivoty = 10                  
        self.rey_coiny = 0                
        self.karty_v_ruce = []            
        self.vylozene_karty = []          
        self.utok_bonus = 0               
        self.muze_pouzit_schopnost = True  
        self.debuffs = []                 
        self.uzivatel = None              
        self.schopnost_rey_aktivni = False
        self.schopnost_sokol_pripravena = False 
        self.ma_ochranny_stit = False 
        self.schopnost_pouzita_v_tahu = False 
        self.schopnost_jiz_pouzita = False 
        self.pokus_o_aktivaci_vycerpan = False 


    # --- METODY PRO LOGIKU TAHU ---

    def ruda_postavy(self):
        """Vrátí typ rudy, který aktivuje schopnost postavy."""
        key = next((k for k, p in POSTAVY.items() if p.nazev == self.postava.nazev), None)
        return self.RUDY_POSTAV.get(key)
        
    def je_aktivacni_ruda(self, karta: 'Karta') -> bool:
        """Zkontroluje, zda daná karta odpovídá rudě postavy pro aktivaci schopnosti."""
        pozadovana_ruda = self.ruda_postavy()
        return karta.rarita == pozadovana_ruda
        
    def aktivovat_schopnost(self, typ_aktivace: str):
        """Aktivace schopnosti postavy — každá postava JEDNOU za tah."""

        URL_REY = "https://i.postimg.cc/PrMfS3rM/DIL-42.jpg"
        URL_LUCIE = "https://i.postimg.cc/DwHZtxR2/31.jpg"
        URL_ONDRA = "https://i.postimg.cc/jSm5GMBT/68.jpg"
        URL_ALES = "https://i.postimg.cc/cL2HVFPS/87.jpg"

        # --- 1) Zabraň opakovanému použití ---
        if self.schopnost_jiz_pouzita:
            # Vracíme (text, URL=None)
            return "❌ Schopnost už byla v tomto tahu použita!", None

        # --- 2) REY KORANTENG ---
        if self.postava.nazev == POSTAVY["rey_koranteng"].nazev:
            self.schopnost_rey_aktivni = True
            self.schopnost_jiz_pouzita = True
            # Vracíme (text, URL Reye)
            return "🔥 **Reyův macek aktivován!** Zvyšuje útok o **+3** pro tento tah.", URL_REY


        # --- 3) LUCIE BORHYOVÁ ---
        if self.postava.nazev == POSTAVY["lucie_borhyova"].nazev:
            self.zivoty = min(10, self.zivoty + 3) # Max 10 HP
            self.schopnost_jiz_pouzita = True
            # Vracíme (text, URL Lucie)
            return f"💛 **Blonďatý šarm aktivován!** získává **+3 životy!** Má nyní {self.zivoty}/10 životů.", URL_LUCIE

        # --- 4) ONDRA SOKOL ---
        if self.postava.nazev == POSTAVY["ondra_sokol"].nazev:
            self.schopnost_sokol_pripravena = True
            self.schopnost_jiz_pouzita = True
            # Vracíme (text, URL Ondry)
            return "🦅 **Sokolí tah aktivován!** Můžeš ukrást až 2 karty.", URL_ONDRA

        # --- 5) ALEŠ HÁMA ---
        if self.postava.nazev == POSTAVY["ales_hama"].nazev:
            self.ma_ochranny_stit = True
            self.schopnost_jiz_pouzita = True
            # Vracíme (text, URL Aleše)
            return "🛡 **Dvakrát víc nebo nic aktivováno!** Zablokuje příští 3 DMG.", URL_ALES
        
        # Pokud se nic neaktivuje
        return "Schopnost se nepodařilo aktivovat.", None

        # --- Fallback ---
        self.schopnost_jiz_pouzita = True
        return f"Schopnost aktivována ({typ_aktivace})."

    def standard_liznout_kartu(self, hra: 'Hra'): 
        """Vezme kartu z balíčku a přidá ji do ruky hráče (standardní líznutí v tahu)."""
        if hra.hlavni_balicek:
            karta = hra.hlavni_balicek.pop(0)
            self.karty_v_ruce.append(karta)
            return karta
        return Karta("Prazdny balicek", "System") 
        
    def risk_liznout_kartu(self, hra: 'Hra'): 
        """Vezme kartu z balíčku POUZE pro risk. Neukládá ji do ruky a odhodí."""
        if hra.hlavni_balicek:
            karta = hra.hlavni_balicek.pop(0)
            hra.odhazovaci_balicek.append(karta) # Karta se zahazuje
            return karta
        return Karta("Prazdny balicek", "System")
        
    def utok_damage(self):
        """Vypočítá poškození na základě Reyho aktivní schopnosti."""
        dmg = 1
        if self.postava.nazev == POSTAVY["rey_koranteng"].nazev and self.schopnost_rey_aktivni:
            dmg += 3 # Rey bonus
        return dmg


class Hra:
    """Hlavní třída pro správu stavu jedné hry"""
    def __init__(self, kanal_id, hraci):
        self.kanal_id = kanal_id
        self.hraci = hraci 
        self.aktualni_hrac_index = 0
        self.hlavni_balicek = []
        self.odhazovaci_balicek = []
        self.stav_souboje = None 
        self.vytvor_balicek()
        self.zamichej_a_rozdej()

    def vytvor_balicek(self):
        """Naplní hlavní balíček Příšerami, Akcemi a Permanentními kartami s náhodnou Rudou."""
        
        # --- NOVÝ SEZNAM AKČNÍCH KARET (Typ: Akce) ---
        # Tyto karty jsou jednorázové a jsou v balíčku 5x (nahrazují Poklady)
        akcni_karty_pokladove_def = [
            ("Studna, ale připadá nám zbytečná", 
             "Získáš 1 ReyCoin. (5x v balíčku)"), 
            ("Koukejte jakého macka jsem ulovil", 
             "Získáš 2 ReyCoiny. (5x v balíčku)"), 
            ("Silné lektvary ve vlastním domě?!", 
             "Vyléčí 2 srdíčka. (2x v balíčku - původní Lektvar)"),
            ("Už jsme hrozně blízko", 
             "Získá 1 Ender oko. (2x v balíčku - původní Blízko)"),
            ("Jsem úplný pirát 🏴‍☠️", 
             "Vezme 1 náhodnou kartu od každého hráče. (2x v balíčku - původní Pirátský poklad)"),
            # Původní Jídlo bude vykládací kartou, takže zde chybí.
        ]
        
        # Sestavíme balíček "Akce" (jednorázové)
        akcni_karty = []
        
        # Karty, které mají 5 kopií (původní Poklady)
        for nazev, efekt in akcni_karty_pokladove_def[:2]: # První dvě karty z definice mají 5x kopii
            for _ in range(5):
                ruda = random.choice(RUDY_POKLDADU)
                akcni_karty.append(Karta(nazev, "Akce", ruda, efekt_text=efekt))

        # Karty, které mají 2 kopie (původní Akce)
        for nazev, efekt in akcni_karty_pokladove_def[2:]: # Zbylé akční karty mají 2x kopii
             for _ in range(2): 
                ruda = random.choice(RUDY_POKLDADU) 
                akcni_karty.append(Karta(nazev, "Akce", ruda, efekt_text=efekt))


        # --- NOVÉ VYKLÁDACÍ KARTY (Typ: Permanentka) ---
        # Tyto karty zůstávají ve hře po vyložení.
        permanentni_karty_def = [
            ("Zvládl jsem to a získal totem", 
             "Permanentka", 
             "Když HP klesne na 0, vyléčí na 3. (Původní Totem)"),
            ("Získal jsem trojzubec a hodlám ho pořádně využít", 
             "Permanentka", 
             "Dává +1 útok ke každému tvému útoku. (Původní Jídlo)"), # Nový efekt pro Trojzubec
            ("S pejskem Avatarem", 
             "Permanentka", 
             "Vždy, když zaútočíš, dává tvému oponentovi -1 do obrany. (Zcela nová karta)"),
        ]

        permanentni_karty = []
        for nazev, typ, efekt in permanentni_karty_def:
            for _ in range(2): # 2x každá, celkem 6 karet
                ruda = random.choice(RUDY_POKLDADU) 
                permanentni_karty.append(Karta(nazev, typ, ruda, efekt_text=efekt))


        # --- PŘÍŠERY (Typ: Příšera, ponechány beze změny) ---
        prisery_def = [
            ("Zombie", 3, 5, 1, "Získáte 1 kartu pokladu."),
            ("Creeper", 5, 5, 1, "Získáte 2 karty pokladu."),
            ("Enderman", 6, 8, 2, "Získáte 2 karty pokladu."),
            ("Vindictor", 7, 10, 2, "Získáte 3 karty pokladu."),
        ]
        prisery = []
        for nazev, utok, zivoty, odmena, efekt in prisery_def:
            for _ in range(2): # 2x každá, celkem 8 karet
                ruda = random.choice(RUDY_POKLDADU) 
                prisery.append(Karta(nazev, "Příšera", ruda, utok, zivoty, odmena, efekt))

        # Finalizace balíčku
        # Celkem 10 (nové Akce 5x) + 6 (Akce 2x) + 6 (Permanentky) + 8 (Příšery) = 30 karet
        self.hlavni_balicek = akcni_karty + permanentni_karty + prisery
        random.shuffle(self.hlavni_balicek)

    def zamichej_a_rozdej(self):
        """Rozdá 5 karet každému hráči (používá pop, ne standard_liznout_kartu)"""
        
        for hrac in self.hraci:
            for _ in range(5):
                if self.hlavni_balicek:
                    hrac.karty_v_ruce.append(self.hlavni_balicek.pop(0))
    
    def aktualni_hrac(self):
        """Vrátí objekt hráče, který je aktuálně na tahu"""
        return self.hraci[self.aktualni_hrac_index]
        
    def get_next_player(self, current_hrac):
        """Najde dalšího hráče v rotaci a nastaví index."""
        try:
            current_index = self.hraci.index(current_hrac)
        except ValueError:
            return self.hraci[0]

        self.aktualni_hrac_index = (current_index + 1) % len(self.hraci)
        return self.hraci[self.aktualni_hrac_index]
        
    async def zahajit_standardni_tah_po_aktivaci(self, interaction: discord.Interaction):
        """Spustí standardní TahView pro aktuálního hráče po dokončení speciální akce."""
        hrac = self.aktualni_hrac() 
        
        # 1. Vygeneruje seznam karet pro soukromou zprávu
        karty_text = "\n".join(
            f"**{i+1}.** {karta.nazev} ({karta.typ}) (Ruda: {karta.rarita})"
            for i, karta in enumerate(hrac.karty_v_ruce)
        )
        karty_zprava = (
            f"**{hrac.uzivatel.mention}**, tvoje karty v ruce:\n"
            f"```markdown\n{karty_text}\n```"
        )
        
        # 2. Odesílá soukromou (ephemeral) zprávu, kterou vidí JEN hráč na tahu
        await interaction.followup.send( 
            content=karty_zprava + "\n**Co chceš udělat v tomto tahu?**",
            view=TahView(self, hrac),
            ephemeral=True
        )


# ===============================================
# C) POMOCNÉ FUNKCE
# ===============================================

async def zobraz_stav_tahu(hra: Hra, hrac_uzivatel: discord.Member):
    """Zobrazí stav tahu do kanálu a spustí Fázi Aktivace."""
    
    hrac_obj = next((h for h in hra.hraci if h.id == hrac_uzivatel.id), None)
    if not hrac_obj:
        return

    kanal = bot.get_channel(hra.kanal_id)
    
    # Resetuje stav pro další kolo
    hrac_obj.schopnost_rey_aktivni = False
    hrac_obj.schopnost_sokol_pripravena = False 
    hrac_obj.schopnost_pouzita_v_tahu = False 
    hrac_obj.schopnost_jiz_pouzita = False 
    hrac_obj.pokus_o_aktivaci_vycerpan = False 
    
    # --- ODSTRANĚNO: Kód pro generování karty_text a prehled_zpravy je pryč ---
    # Karty se nyní zobrazují jen v ephemeral zprávě po volbě tahu (v zahajit_standardni_tah_po_aktivaci)
    # --------------------------------------------------------------------------

    # Veřejný embed (Stav Hry)
    stav_embed = discord.Embed(
        title=f"⚔️ {hrac_uzivatel.display_name} | JSI NA TAHU",
        description=(
            f"Používáš postavu: **{hrac_obj.postava.nazev}** "
            f"(Ruda pro aktivaci: **{hrac_obj.ruda_postavy()}**).\n"
            f"**Útok v tomto kole: {hrac_obj.utok_damage()}**"
        ),
        color=0x008080
    )

    # 1. Definice emoji (používá vaše ID)
    VLASTNI_EMOJI_ZIVOTY = "<:zivoty:1441775393454424095>"
    VLASTNI_EMOJI_REYCOIN = "<:REYCOIN:1295023128531173407>"

    # 2. Políčka embedů
    stav_embed.add_field(
        name=f"{VLASTNI_EMOJI_ZIVOTY} Životy",
        value=f"{hrac_obj.zivoty}/10"
    )

    stav_embed.add_field(
        name=f"{VLASTNI_EMOJI_REYCOIN} ReyCoiny",
        value=hrac_obj.rey_coiny
    )

    stav_embed.add_field(
        name="Karet v ruce",
        value=len(hrac_obj.karty_v_ruce)
    )

    if hrac_obj.ma_ochranny_stit:
        stav_embed.add_field(
            name="🛡️ Štít",
            value="Aktivní (blokuje 3 DMG)"
        )

   # ... (kód s definicemi stav_embed.add_field zůstává beze změny) ...
    
    # ⬇️ KROK 1: VEŘEJNÁ zpráva s přehledem stavu a volbou tahu (Fáze Aktivace)
    # Tato zpráva obsahuje základní info a tlačítka Risk/Standardní Tah
    await kanal.send(
        content=f"**{hrac_obj.uzivatel.mention}**, JSI NA TAHU. Zvol si, zda riskuješ a aktivuješ schopnost.", 
        embed=stav_embed,
        view=FazeAktivaceView(hra, hrac_obj)
    )
    
    # ⬇️ KROK 2: VEŘEJNÁ zpráva s tlačítkem POUZE pro zobrazení karet
    # Hráč může kliknout na toto tlačítko kdykoli před volbou tahu a zobrazí si karty soukromě.
    await kanal.send(
        content=f"**{hrac_obj.uzivatel.mention}**, Pro zobrazení tvé ruky klikni na tlačítko níže (uvidíš ji jen ty):",
        view=ZobrazKartyView(hrac_obj)
    )

async def spustit_hru(kanal: discord.TextChannel, hrac1: discord.Member, hrac2: discord.Member):
    """Inicializuje hru po výběru postav a rozdá karty."""
    kanal_id = kanal.id
    
    if kanal_id not in aktivni_hry:
        
        postava1_nazev = vyber_postavy.get(hrac1.id, "rey_koranteng")
        postava2_nazev = vyber_postavy.get(hrac2.id, "lucie_borhyova")

        hrac_obj1 = Hrac(hrac1.id, POSTAVY[postava1_nazev])
        hrac_obj1.uzivatel = hrac1 
        
        hrac_obj2 = Hrac(hrac2.id, POSTAVY[postava2_nazev])
        hrac_obj2.uzivatel = hrac2 
        
        nova_hra = Hra(kanal_id, [hrac_obj1, hrac_obj2])
        aktivni_hry[kanal_id] = nova_hra
        
        prvni_hrac_uzivatel = nova_hra.aktualni_hrac().uzivatel
        
        await kanal.send(f"***--- ZAČÁTEK HRY REY V MINECRAFTU ---***\n"
                         f"**{hrac1.display_name}** hraje za **{hrac_obj1.postava.nazev}** ({hrac_obj1.ruda_postavy()}).\n"
                         f"**{hrac2.display_name}** hraje za **{hrac_obj2.postava.nazev}** ({hrac_obj2.ruda_postavy()}).\n"
                         f"**Rozdáno 5 karet. Na tahu je: {prvni_hrac_uzivatel.mention}**")
                         
        await zobraz_stav_tahu(nova_hra, prvni_hrac_uzivatel)
        
    else:
         await kanal.send("Chyba: Hra již probíhá na tomto kanále.")

# Nová funkce pro ukončení hry (Vzdát se)
async def ukoncit_hru_vyhra(kanal_id, vitez_uzivatel: discord.Member, porazeny_uzivatel: discord.Member):
    """Ukončí hru a vyhlásí vítěze a poraženého."""
    if kanal_id in aktivni_hry:
        del aktivni_hry[kanal_id]
        kanal = bot.get_channel(kanal_id)
        if kanal:
            await kanal.send(
                f"🎉 **{vitez_uzivatel.display_name} VYHRÁVÁ!**\n"
                f"**{porazeny_uzivatel.display_name}** se vzdal/a."
            )


# ===============================================
# D) DISCORD KOMPONENTY (VIEWS/TLAČÍTKA)
# ===============================================

class DiscardAbilitySelectView(discord.ui.View):
    """Dočasné view pro výběr karty k odhození a aktivaci schopnosti."""
    def __init__(self, tah_view_instance, hrac: 'Hrac', required_ruda: str):
        super().__init__(timeout=120)
        self.tah_view = tah_view_instance # Odkaz na původní TahView
        self.hrac = hrac
        self.required_ruda = required_ruda
        
    async def select_callback(self, interaction: discord.Interaction):
        
        # Ochrana proti zneužití (i když by tlačítko mělo být skryté)
        if self.hrac.schopnost_jiz_pouzita:
            self.stop()
            return await interaction.response.send_message("❌ Schopnost už byla v tomto tahu použita!", ephemeral=True)
            
        # Zastavíme toto dočasné view
        self.stop()
            
        selected_index = int(interaction.data['values'][0])
        
        # 1. Odhoď kartu
        discarded_card = self.hrac.karty_v_ruce.pop(selected_index)
        self.tah_view.hra.odhazovaci_balicek.append(discarded_card)
        
        # 2. Aktivuj schopnost (nastaví příznaky a schopnost_jiz_pouzita = True)
        zprava_aktivace, url_obrazku = self.hrac.aktivovat_schopnost("Odhozením")
        
        self.hrac.pokus_o_aktivaci_vycerpan = True # Aktivace odhozením vyčerpá pokus

        # 3. Public message (NOVÉ: Vytvoříme Embed)
        aktivace_embed = discord.Embed(
            title="🔥 SCHOPNOST AKTIVOVÁNA ODHOZENÍM!",
            description=f"**{self.hrac.uzivatel.display_name}**: {zprava_aktivace}",
            color=discord.Color.orange()
        )
        if url_obrazku:
            aktivace_embed.set_image(url=url_obrazku)
        
        # Původní await interaction.channel.send nahradíme posláním Embedu
        await interaction.channel.send(embed=aktivace_embed)
        
        # 4. Update the original TahView message
        zprava = f"**Schopnost aktivována.** Karta {discarded_card.nazev} byla odhozena."
        # Důležité: is_main_action=False, protože aktivace odhozením je bonusová akce
        await self.tah_view.aktualizovat_view_po_akci(interaction, zprava, is_main_action=False)


class OndraSokolView(discord.ui.View):
    """View pro výběr karet, které Ondra Sokol ukradne oponentovi."""
    def __init__(self, hra: 'Hra', hrac: 'Hrac', oponent: 'Hrac'):
        super().__init__(timeout=120)
        self.hra = hra
        self.hrac = hrac
        self.oponent = oponent
        self.max_cards_to_steal = min(2, len(oponent.karty_v_ruce))
        
        if self.max_cards_to_steal > 0:
            self.add_item(self.create_card_select())
        else:
            # Tlačítko Dokončit se zobrazí, pokud není co krást
            self.add_item(self.finish_button) 

    def create_card_select(self):
        """Vytvoří Select menu s číslovanými prázdnými sloty oponentovy ruky."""
        options = [
            discord.SelectOption(label=f"Karta {i+1}", value=str(i))
            for i in range(len(self.oponent.karty_v_ruce))
        ]
        
        select = discord.ui.Select(
            placeholder=f"Zvol karty ke krádeži (max {self.max_cards_to_steal})...", 
            options=options,
            min_values=1,
            max_values=self.max_cards_to_steal,
            custom_id="sokol_card_steal"
        )
        select.callback = self.select_callback
        return select

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.hrac.id:
            return await interaction.response.send_message("To není tvůj tah!", ephemeral=True)
            
        selected_indices = [int(v) for v in interaction.data['values']]
        
        ukradene_karty = []
        selected_indices.sort(reverse=True) 
        
        for index in selected_indices:
            karta = self.oponent.karty_v_ruce.pop(index)
            self.hrac.karty_v_ruce.append(karta)
            ukradene_karty.append(karta.nazev)
            
        ukradene_nazvy = ", ".join(ukradene_karty)
        
        # Veřejná zpráva
        await interaction.channel.send(
            f"💥 **Sokolí tah!** {self.hrac.uzivatel.mention} ukradl {len(ukradene_karty)} karet od {self.oponent.uzivatel.display_name}. Ukradené karty: {ukradene_nazvy}."
        )

        # Ukončení a editace veřejné zprávy. Hráč se vrací do TahView (ephemeral).
        await interaction.response.edit_message(
            content=f"✅ Krádež provedena! Krádež skončila. Pokračuj v tahu v privátním okně.",
            view=None
        )
        self.stop()
        
    @discord.ui.button(label="Oponent nemá karty k ukradení / Dokončit", style=discord.ButtonStyle.secondary, custom_id="sokol_finish")
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Sokolí tah ukončen. Pokračuj v tahu v privátním okně.",
            view=None
        )
        self.stop()
        
    async def on_timeout(self):
        self.clear_items()
        self.stop()
        kanal = bot.get_channel(self.hra.kanal_id)
        if kanal:
             await kanal.send(f"**{self.hrac.uzivatel.mention}**, vypršel čas na krádež. Pokračuješ standardním tahem.")

class VyberPostavuView(discord.ui.View):
    """View pro výběr postavy na začátku hry."""
    
    def __init__(self, hrac_id, vyzyvatel: discord.Member, vyzvana: discord.Member, bot_instance, channel_id, *args, **kwargs): 
        super().__init__(timeout=120)
        self.hrac_id = hrac_id
        self.vyzyvatel = vyzyvatel
        self.vyzvana = vyzvana
        self.bot = bot_instance
        self.channel_id = channel_id 
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.hrac_id: 
            await interaction.response.send_message("Tato volba není určena pro tebe!", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="Zvol si svou postavu...", 
        options=[
            discord.SelectOption(label=p.nazev, value=key) 
            for key, p in POSTAVY.items()
        ],
        custom_id="vyber_postavy_select"
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        
        global vyber_postavy
        global dostupne_postavy_stav
        value = select.values[0] 
        
        if value not in dostupne_postavy_stav.get(self.channel_id, []):
            await interaction.response.send_message(f"Postava **{POSTAVY[value].nazev}** již byla vybrána jiným hráčem. Zvol si jinou.", ephemeral=True)
            return
            
        vyber_postavy[self.hrac_id] = value
        dostupne_postavy_stav[self.channel_id].remove(value) 
        
        await interaction.response.edit_message(
            content=f"✅ **{interaction.user.display_name}** si zvolil postavu: **{POSTAVY[value].nazev}**.",
            view=None
        )
        
        hrac1_vybral = self.vyzyvatel.id in vyber_postavy
        hrac2_vybral = self.vyzvana.id in vyber_postavy
        
        if hrac1_vybral and hrac2_vybral:
            await interaction.channel.send("Oba hráči si zvolili postavu. Spouštím hru...")
            del dostupne_postavy_stav[self.channel_id] 
            await spustit_hru(interaction.channel, self.vyzyvatel, self.vyzvana)
        else:
            cekajici_hrac = self.vyzvana.display_name if self.hrac_id == self.vyzyvatel.id else self.vyzyvatel.display_name
            await interaction.channel.send(f"Čeká se na výběr postavy od **{cekajici_hrac}**.")


class VyzvaView(discord.ui.View):
    """View pro přijetí/odmítnutí výzvy"""
    
    def __init__(self, vyzyvatel: discord.Member, vyzvana: discord.Member, bot_instance, *args, **kwargs):
        super().__init__(timeout=60) 
        self.vyzyvatel = vyzyvatel
        self.vyzvana = vyzvana
        self.bot = bot_instance
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.vyzvana.id:
            await interaction.response.send_message("Tato výzva není určena pro tebe!", ephemeral=True)
            return False
        return True
        
    @discord.ui.button(label="Přijmout", style=discord.ButtonStyle.green)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"**{self.vyzvana.display_name}** přijal výzvu! Nyní si vyberte postavy.", view=None)
        
        channel_id = interaction.channel.id
        global dostupne_postavy_stav
        dostupne_postavy_stav[channel_id] = list(POSTAVY.keys())

        await interaction.channel.send(f"**{self.vyzyvatel.display_name}**, zvol si postavu:", 
                                     view=VyberPostavuView(self.vyzyvatel.id, self.vyzyvatel, self.vyzvana, self.bot, channel_id))
                                     
        await interaction.channel.send(f"**{self.vyzvana.display_name}**, zvol si postavu:", 
                                     view=VyberPostavuView(self.vyzvana.id, self.vyzyvatel, self.vyzvana, self.bot, channel_id))
        self.stop()
        
    @discord.ui.button(label="Odmítnout", style=discord.ButtonStyle.red)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"**{self.vyzvana.display_name}** odmítl výzvu. 😔", view=None)
        self.stop()


class FazeAktivaceView(discord.ui.View):
    """První fáze tahu: Výběr mezi Riskem (Líznutím) nebo Standardním Tahem."""
    def __init__(self, hra, hrac):
        super().__init__(timeout=90)
        self.hra = hra
        self.hrac = hrac
        
        # NOVÁ KONTROLA: Zabrání vícenásobné aktivaci v tomto tahu
        if self.hrac.schopnost_jiz_pouzita:
            self.risk_a_liznout.disabled = True
            self.standardni_tah.label = "➡️ Standardní Tah (Schopnost už aktivní)"
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.hrac.id:
             await interaction.response.send_message("Nyní nejsi na tahu.", ephemeral=True)
             return False
        return True

    @discord.ui.button(label="🎲 Riskovat a Líznout kartu (Možná Aktivace)", style=discord.ButtonStyle.blurple, custom_id="risk_a_liznout")
    async def risk_a_liznout(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        # Kontrola, že Risk nebyl zablokován
        if self.hrac.schopnost_jiz_pouzita:
            return await interaction.response.send_message("❌ Schopnost už byla v tomto tahu použita!", ephemeral=True)

        # 1. Editujeme původní zprávu
        await interaction.response.edit_message(content=f"**{self.hrac.uzivatel.display_name}** riskuje a líže vrchní kartu...", view=None)
        
        # 2. Líznout kartu ( NEPŘIDÁ SE do ruky, zahodí se)
        karta_liznuta = self.hrac.risk_liznout_kartu(self.hra)
        
        # 3. Kontrola rudy a aktivace schopnosti
        if not self.hrac.schopnost_jiz_pouzita and self.hrac.je_aktivacni_ruda(karta_liznuta):
            # Scénář A: ÚSPĚŠNÝ RISK
            
            self.hrac.pokus_o_aktivaci_vycerpan = True
            
            # NOVÉ: Zachytíme text A URL
            zprava_aktivace, url_obrazku = self.hrac.aktivovat_schopnost("Líznutím") 
            
            # NOVÉ: Vytvoříme Embed
            aktivace_embed = discord.Embed(
                title="🔥 SCHOPNOST AKTIVOVÁNA LÍZNUTÍM!",
                description=f"**{self.hrac.uzivatel.display_name}**: {zprava_aktivace}",
                color=discord.Color.gold()
            )
            if url_obrazku:
                aktivace_embed.set_image(url=url_obrazku)
                
            # Původní await interaction.channel.send nahradíme posláním Embedu
            await interaction.channel.send(embed=aktivace_embed)
            
        elif self.hrac.schopnost_jiz_pouzita:
            # Tento stav by neměl nastat, pokud je tlačítko disabled
            await interaction.channel.send(f"**{self.hrac.uzivatel.mention}**: Schopnost už byla v tomto tahu použita. Karta byla zahozena.")
            
        else:
            # Scénář B: NEÚSPĚŠNÁ AKTIVACE
            
            # KLÍČOVÝ KROK 3: Vyčerpáme POKUS, ačkoliv schopnost není aktivní
            self.hrac.pokus_o_aktivaci_vycerpan = True
            
            await interaction.channel.send(f"**{self.hrac.uzivatel.mention}**: Líznuto: **{karta_liznuta.nazev}** (Ruda: {karta_liznuta.rarita}). **Schopnost se neaktivuje.** Karta byla zahozena.")
            
        # 4. Spuštění standardního tahu (používá followup)
        # Tímto voláním se přejde na hlavní TahView
        await self.hra.zahajit_standardni_tah_po_aktivaci(interaction)

    @discord.ui.button(label="➡️ Standardní Tah", style=discord.ButtonStyle.green, custom_id="standardni_tah")
    async def standardni_tah(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Standardní tah = Risk nebyl proveden, odhození je povoleno.
        # Odstraněno nastavení self.hrac.muze_pouzit_schopnost/schopnost_jiz_pouzita, jelikož se resetuje v zobraz_stav_tahu
        self.hrac.pokus_o_aktivaci_vycerpan = False # Nastavíme na False, jelikož Risk nebyl proveden

        # 1. Editujeme původní zprávu
        await interaction.response.edit_message(content=f"**{self.hrac.uzivatel.display_name}** zahajuje standardní tah.", view=None)
        
        # 2. Spuštění standardního tahu (používá followup)
        await self.hra.zahajit_standardni_tah_po_aktivaci(interaction)

# KLÍČOVÁ OPRAVA JE ZDE
class TahView(discord.ui.View):
    """View pro hlavní fázi tahu (Líznout/Zaútočit/Konec Tahu)"""
    
    def __init__(self, hra: Hra, hrac: Hrac):
        # Po inicializaci super().__init__() jsou dekorované metody (tlačítka) dostupné jako atributy.
        super().__init__(timeout=120) 
        self.hra = hra
        self.hrac = hrac
        self.main_action_used = False # Sledování, zda byla použita hlavní akce
        
        # Nyní voláme po inicializaci
        self.pridat_akcni_tlacitka() 
        
    def pridat_akcni_tlacitka(self):
        """Dynamicky přidává tlačítka podle stavu tahu."""
        self.clear_items()
        
        # Hlavní akce (pouze pokud nebyla použita)
        if not self.main_action_used:
            self.add_item(self.liznout_v_tahu_button)
            self.add_item(self.utok_oponent_button)
            
        # Tlačítko Aktivace odhozením je zobrazeno POUZE pokud schopnost NEBYLA POUŽITA 
        # A POKUS O AKTIVACI RISKem NEBYL VYČERPÁN A má kartu
        # >>> NAHRAZENÝ ŘÁDEK <<<
        if not self.hrac.schopnost_jiz_pouzita and not self.hrac.pokus_o_aktivaci_vycerpan and any(k.rarita == self.hrac.ruda_postavy() for k in self.hrac.karty_v_ruce):
            self.add_item(self.aktivovat_schopnost_tlacitko)
            
        # TLAČÍTKO PRO SOKOLÍ TAH
        if self.hrac.postava.nazev == POSTAVY["ondra_sokol"].nazev and self.hrac.schopnost_sokol_pripravena:
            self.add_item(self.pouzit_sokol_button)
        
        # Nové tlačítko pro vzdání se
        self.add_item(self.vzdani_se_button)
        
        # Tlačítko Konec Tahu
        self.add_item(self.konec_tahu_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.hrac.id:
            await interaction.response.send_message("Nyní nejsi na tahu.", ephemeral=True)
            return False
        return True
        
    async def aktualizovat_view_po_akci(self, interaction: discord.Interaction, zprava: str, ukoncit_hru=False, is_main_action=True):
        """Nastaví view do stavu 'Hlavní akce použita' a aktualizuje zprávu."""
        
        if ukoncit_hru:
            self.stop()
            # Můžeme použít followup.edit_message, pokud byla interakce zodpovězena dříve.
            if interaction.response.is_done():
                 await interaction.followup.edit_message(message_id=interaction.message.id, content=f"**HRA SKONČILA!**\n{zprava}", view=None)
            else:
                 await interaction.response.edit_message(content=f"**HRA SKONČILA!**\n{zprava}", view=None)
            return
            
        if is_main_action:
            self.main_action_used = True
            
        # VYNUCENÉ PŘEKRESLENÍ TLAČÍTEK
        self.pridat_akcni_tlacitka() 
        
        # Aktualizace ephemeral zprávy
        karty_text = "\n".join(
            f"**{i+1}.** {karta.nazev} ({karta.typ}) (Ruda: {karta.rarita})"
            for i, karta in enumerate(self.hrac.karty_v_ruce)
        )
        
        novy_obsah = f"**TVOJE KARTY V RUCE:**\n{karty_text}\n\n**Co chces udelat v tomto tahu?**\n\n_Akce provedena: {zprava}_"

        # Kontrola, zda interakce již nebyla zodpovězena 
        if interaction.response.is_done():
            # Použijeme follow up, pokud byla interakce zodpovězena dříve (např. v rámci select menu DiscardAbilitySelectView)
            await interaction.followup.edit_message(message_id=interaction.message.id, content=novy_obsah, view=self)
        else:
             await interaction.response.edit_message(
                content=novy_obsah,
                view=self
            )


    @discord.ui.button(label="📜 Líznout kartu", style=discord.ButtonStyle.primary, custom_id="liznout_v_tahu_button", row=0)
    async def liznout_v_tahu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Líznout kartu (standardní)
        karta = self.hrac.standard_liznout_kartu(self.hra) 
        zprava = f"📜 **Líznul jsi kartu:** {karta.nazev} ({karta.typ}) (Ruda: {karta.rarita}). Nyní máš karet: **{len(self.hrac.karty_v_ruce)}**."
        await self.aktualizovat_view_po_akci(interaction, zprava, is_main_action=True)

    @discord.ui.button(label="⚔️ Zaútočit na oponenta", style=discord.ButtonStyle.red, custom_id="utok_oponent_button", row=0)
    async def utok_oponent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        oponent = next(h for h in self.hra.hraci if h.id != self.hrac.id)
        dmg = self.hrac.utok_damage()
        
        # OCHRANNÝ ŠTÍT ALEŠE HÁMY (Logika: Snížení o 3 DMG)
        blokovano_dmg = 0
        if oponent.ma_ochranny_stit:
            blokovano_dmg = min(3, dmg) # Blokuje max 3 dmg
            oponent.ma_ochranny_stit = False # Spotřebujeme štít
        
        final_dmg = dmg - blokovano_dmg
        
        if final_dmg > 0:
            oponent.zivoty -= final_dmg
            # KLÍČOVÁ ZMĚNA: Životy nikdy neklesnou pod nulu před koncem hry
            oponent.zivoty = max(0, oponent.zivoty)
            
        if blokovano_dmg > 0:
             zprava_stit = f"(🛡️ Štít Aleše Hámy zablokoval {blokovano_dmg} DMG!)"
        else:
             zprava_stit = ""
             
        zprava = f"💥 **Zaútočil jsi!** Způsobené poškození: **{final_dmg}** {zprava_stit}. Oponent **{oponent.uzivatel.display_name}** má {oponent.zivoty}/10 životů."
        
        # Veřejná zpráva o útoku
        if blokovano_dmg > 0:
            await interaction.channel.send(f"**{self.hrac.uzivatel.mention}** útočí na **{oponent.uzivatel.mention}** za {dmg} poškození! **Štít oponenta blokuje {blokovano_dmg} DMG.** Oponent má **{oponent.zivoty}/10** životů.")
        else:
            await interaction.channel.send(f"**{self.hrac.uzivatel.mention}** útočí na **{oponent.uzivatel.mention}** za {final_dmg} poškození! Oponent má **{oponent.zivoty}/10** životů.")

        # Konec hry
        if oponent.zivoty <= 0:
            # Veřejná zpráva o vítězství
            await interaction.channel.send(f"**🥳 {self.hrac.uzivatel.mention} VYHRÁVÁ!**\n"
                                          f"**{oponent.uzivatel.display_name}** byl poražen (0/10 HP).")
            # Ukončení hry
            if self.hra.kanal_id in aktivni_hry:
                del aktivni_hry[self.hra.kanal_id]
                
            await self.aktualizovat_view_po_akci(interaction, zprava, ukoncit_hru=True, is_main_action=True)
            return

        # Po útoku se přepne stav View na Konec Tahu
        await self.aktualizovat_view_po_akci(interaction, zprava, is_main_action=True)
        
    @discord.ui.button(label="🦅 Použít Sokolí tah (Krádež)", style=discord.ButtonStyle.blurple, custom_id="pouzit_sokol_tah", row=1)
    async def pouzit_sokol_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        oponent = next(h for h in self.hra.hraci if h.id != self.hrac.id)
        
        # Označíme, že schopnost byla použita
        self.hrac.schopnost_sokol_pripravena = False 
        
        if len(oponent.karty_v_ruce) > 0:
            # Spustíme veřejnou zprávu s výběrem
            await interaction.response.send_message(
                f"**{self.hrac.uzivatel.mention}**, Sokolí tah aktivován. Zvol, které karty ukradneš od **{oponent.uzivatel.display_name}**.",
                view=OndraSokolView(self.hra, self.hrac, oponent),
                ephemeral=False 
            )
            # Vrátíme se do hlavního TahView bez tlačítka pro krádež
            zprava = "Sokolí tah spuštěn (následuje krádež ve veřejné zprávě)."
            
        else:
            # Krádež není možná
            zprava = "Sokolí tah: Oponent nemá karty k ukradení."
            await interaction.response.send_message(f"**{self.hrac.uzivatel.mention}**, oponent nemá karty k ukradení.", ephemeral=True)
        
        # Aktualizujeme ephemeral TahView po použití bonusové akce
        await self.aktualizovat_view_po_akci(interaction, zprava, is_main_action=False)


    @discord.ui.button(label="Aktivovat schopnost (Odhozením karty)", style=discord.ButtonStyle.secondary, custom_id="aktivovat_odhozenim_button", row=1)
    async def aktivovat_schopnost_tlacitko(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        # ZABEZPEČENÍ ZNOVU - PRO JISTOTU
        if self.hrac.schopnost_jiz_pouzita:
            await self.aktualizovat_view_po_akci(interaction, "❌ Tlačítko se objevilo omylem. Schopnost už byla v tomto tahu použita!", is_main_action=False)
            return

            
        required_ruda = self.hrac.ruda_postavy()
        
        # 1. Filtruj karty k odhození
        discardable_cards = [
            (i, k) for i, k in enumerate(self.hrac.karty_v_ruce) 
            if k.rarita == required_ruda
        ]
        
        if not discardable_cards:
            return await interaction.response.send_message(
                f"Chyba: Nemáš kartu rudy **{required_ruda}** k odhození. Tlačítko se nemělo zobrazit.", ephemeral=True
            )

        # 2. Vytvoř Select menu options
        options = [
            discord.SelectOption(label=f"{karta.nazev} (Ruda: {karta.rarita})", value=str(index))
            for index, karta in discardable_cards
        ]

        # 3. Vytvoř dočasné view s callbackem pro zpracování výběru
        temp_view = DiscardAbilitySelectView(self, self.hrac, required_ruda)
        select = discord.ui.Select(
            placeholder=f"Zvol jednu kartu rudy {required_ruda} k aktivaci schopnosti...", 
            options=options,
            min_values=1,
            max_values=1,
            custom_id="discard_ability_select"
        )
        select.callback = temp_view.select_callback
        temp_view.add_item(select)

        # 4. Nahraď původní Ephemeral zprávu výběrovým menu
        await interaction.response.edit_message(
            content=f"**{self.hrac.uzivatel.mention}**, zvol jednu kartu **{required_ruda}** k aktivaci schopnosti:",
            view=temp_view
        )

    @discord.ui.button(label="🏳️ VZDÁT SE", style=discord.ButtonStyle.danger, custom_id="vzdani_se_button", row=4)
    async def vzdani_se_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        oponent = next(h for h in self.hra.hraci if h.id != self.hrac.id)
        
        # 1. Veřejné oznámení o vzdání se (Zodpovězení interakce)
        # Použijeme response.send_message s ephemeral=False, aby byla veřejná zpráva vidět hned
        await interaction.response.send_message(
            f"**{self.hrac.uzivatel.display_name}** se vzdává! **{oponent.uzivatel.display_name}** vyhrává.",
            ephemeral=False
        )
        
        # 2. Ukončení hry a vyhlášení vítěze v hlavním stavu
        await ukoncit_hru_vyhra(self.hra.kanal_id, oponent.uzivatel, self.hrac.uzivatel)
        self.stop()
        
        # 3. Ukončení ephemeral View (TahView). 
        # Použijeme interaction.followup.edit_message, protože interakce již byla zodpovězena bodem 1.
        # message_id je ID původní efemérní zprávy, které drží interaction.message
        try:
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content="Hra ukončena (Vzdání se).", 
                view=None
            )
        except discord.errors.NotFound:
            # Zachycení chyby 404, pokud efemérní zpráva už byla smazána
            # (V takovém případě už je zpráva pryč a nemusíme nic dělat)
            print("INFO: Efemérní TahView již bylo smazáno, nelze editovat zprávu o vzdání.")
            pass


    @discord.ui.button(label="Konec Tahu", style=discord.ButtonStyle.danger, custom_id="konec_tahu_button", row=4)
    async def konec_tahu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        await interaction.response.edit_message(content="🔚 Tvůj tah skončil. Přesouvám se na dalšího hráče.", view=None)

        dalsi_hrac = self.hra.get_next_player(self.hrac) 
        
        # Reset schopností na další kolo
        dalsi_hrac.schopnost_rey_aktivni = False
        dalsi_hrac.schopnost_sokol_pripravena = False
        dalsi_hrac.schopnost_jiz_pouzita = False 
        dalsi_hrac.pokus_o_aktivaci_vycerpan = False 
        
        await zobraz_stav_tahu(self.hra, dalsi_hrac.uzivatel) 

class ZobrazKartyView(discord.ui.View):
    """Zobrazení, které má pouze tlačítko k zobrazení karet hráče (ephemeral)."""
    def __init__(self, hrac):
        super().__init__(timeout=None)
        self.hrac = hrac

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.hrac.uzivatel.id:
            await interaction.response.send_message("❌ Toto není tvůj tah ani tvé karty.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Zobrazit mé karty (Doporučeno)", style=discord.ButtonStyle.secondary, emoji="🃏")
    async def zobrazit_karty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Generujeme seznam karet
        karty_text = "\n".join(
            f"**{i+1}.** {karta.nazev} ({karta.typ}) (Ruda: {karta.rarita})"
            for i, karta in enumerate(self.hrac.karty_v_ruce)
        )
        karty_zprava = (
            f"**Tvoje karty v ruce:**\n"
            f"```markdown\n{karty_text}\n```"
        )
        
        # Odesíláme soukromou (ephemeral) zprávu
        await interaction.response.send_message(
            content=karty_zprava,
            ephemeral=True
        )


# ===============================================
# E) DISCORD EVENTY A PŘÍKAZY
# ===============================================

@bot.event
async def on_ready():
    print(f'Bot se úspěšně přihlásil jako: {bot.user}')
    print(f'ID bota: {bot.user.id}')
    print('-------------------------------------------')

    try:
        synced = await bot.tree.sync()
        print(f"Zaregistrováno {len(synced)} Slash příkazů.")
    except Exception as e:
        print(f"Chyba při synchronizaci příkazů: {e}")
        
@bot.command()
async def ping(ctx):
    """Testovací příkaz"""
    latency = round(bot.latency * 1000)
    await ctx.send(f'Pong! Latence je {latency}ms.')

@bot.tree.command(name="vyzvat", description="Vyzvi hráče k hře Rey v Minecraftu (1v1).")
@discord.app_commands.describe(hrac="Hráč, kterého vyzýváš.")
async def vyzvat(interaction: discord.Interaction, hrac: discord.Member):
    
    if interaction.channel.id in aktivni_hry:
        return await interaction.response.send_message("Na tomto kanálu už probíhá hra! Nejprve ji dokončete.", ephemeral=True)
        
    if hrac.id == interaction.user.id:
        return await interaction.response.send_message("Nemůžeš vyzvat sebe sama!", ephemeral=True)

    vyzva_text = f"{hrac.mention}, **{interaction.user.display_name}** tě vyzývá k hře **Rey v Minecraftu!**"
    
    await interaction.response.send_message(vyzva_text, 
                                            view=VyzvaView(interaction.user, hrac, interaction.client))

# ===============================================
# F) UPTIME UDRŽENÍ (PRO RENDER)
# ===============================================

app = Flask('')

@app.route('/')
def home():
    # Render kontroluje tuto stránku, aby viděl, že je bot naživu
    return "Bot je spuštěn."

def run_web_server():
    # Spustí web server na portu, který je dynamicky přidělen Renderem
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# ===============================================
# G) SPUŠTĚNÍ - ZABEZPEČENÉ NAČTENÍ TOKENU
# ===============================================

# 1. Pokusíme se načíst token ze systémové proměnné (pro hosting)
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')

if DISCORD_TOKEN is None:
    # 2. Pokud se nenačte, načteme jej z config.py (pouze pro lokální testování)
    try:
        import config
        DISCORD_TOKEN = config.DISCORD_TOKEN
        print("Token načten lokálně z config.py (POZOR: NENÍ BEZPEČNÉ PRO GITHUB)")
    except ImportError:
        # Token nebyl nalezen ani lokálně
        print("\n\n------------------------------------------------------")
        print("CHYBA: Discord Token nebyl nalezen.")
        print("Nastavte proměnnou prostředí 'DISCORD_TOKEN' na hostingu.")
        print("------------------------------------------------------\n\n")
        sys.exit(1)

# ===============================================
# F) SPUŠTĚNÍ - ZABEZPEČENÉ NAČTENÍ TOKENU
# ===============================================

# ... (Kód pro načtení DISCORD_TOKEN zůstává beze změny) ...

if __name__ == "__main__":
    
    # 1. Spustíme webový server v samostatném vlákně
    # Tento server odpovídá na ping Renderu a zabraňuje timeoutu.
    t = threading.Thread(target=run_web_server)
    t.start()
    
    # 2. Spustíme Discord bota v hlavním vlákně
    try:
        print("POKUS O SPOUŠTĚNÍ BOTA...")
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("\n\n------------------------------------------------------")
        print("CHYBA PŘI PŘIHLÁŠENÍ: Token je pravděpodobně neplatný nebo chybí.")
        print("------------------------------------------------------\n\n")
    except Exception as e:
        print(f"Během spouštění došlo k neočekávané chybě: {e}")
        sys.exit(1)