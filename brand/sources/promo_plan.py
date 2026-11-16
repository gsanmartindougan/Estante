"""Bilingual editorial plan. Claims refer to README.md and settings_schema.py."""
CLIPS = [
 ('01-estante',('Tu próxima partida','Your next game'),[
  ('list','Tus juegos, reunidos en una biblioteca para Linux.','Bring your games together in one library for Linux.'),
  ('grid','Steam, Faugus, Heroic y juegos locales.','Steam, Faugus, Heroic and local games.'),
  ('carousel','Elige cómo recorrer tu colección.','Choose how you browse your collection.'),
  ('sense','Mando, teclado o ratón. Tú eliges.','Gamepad, keyboard or mouse. Your choice.')]),
 ('02-biblioteca',('Reúne tus juegos','Bring your games together'),[
  ('imports','Importa Steam, Faugus y Heroic desde Ajustes.','Import Steam, Faugus and Heroic from Settings.'),
  ('local','Añade scripts .sh y AppImages locales.','Add local .sh scripts and AppImages.'),
  ('local','Configura argumentos y directorio de trabajo.','Set launch arguments and the working directory.'),
  ('startup','Elige qué launchers abrir al iniciar Estante.','Choose which launchers open when Estante starts.')]),
 ('03-organiza',('Encuentra tu próxima partida','Find your next game'),[
  ('search','Busca por nombre mientras recorres tu biblioteca.','Search by name as you browse your library.'),
  ('categories','Crea, ordena y edita tus categorías.','Create, reorder and edit your categories.'),
  ('grid','Recorre Grid por páginas; el tamaño es configurable.','Browse Grid by pages, with a configurable page size.'),
  ('list','Navega por selección o salta por inicial.','Move through games or jump by initial.')]),
 ('04-apariencias',('Cuatro formas de explorar','Four ways to browse'),[
  ('list','Lista: una rueda de logos y la ficha del juego.','List: a logo wheel alongside the game details.'),
  ('grid','Grid: carátulas ordenadas y ficha lateral.','Grid: organized covers with details on the side.'),
  ('carousel','Carousel: selección central y navegación circular.','Carousel: centered selection and circular navigation.'),
  ('sense','Sense: una fila compacta sobre el fondo del juego.','Sense: a compact row over the game background.')]),
 ('05-personaliza',('Hazla tuya','Make it yours'),[
  ('editor','Edita la ficha y la sinopsis en el panel lateral.','Edit game details and the synopsis in the side panel.'),
  ('artwork','Elige carátulas, logos y fondos para cada juego.','Choose covers, logos and backgrounds for each game.'),
  ('appearance','Ajusta tamaños, presentación y selección.','Adjust sizes, presentation and selection.'),
  ('background','Configura fondos, divisiones y oscurecimiento.','Configure backgrounds, splits and dimming.')]),
 ('06-controles',('A tu manera','Your way'),[
  ('controls','Elige español o inglés y tu tipo de mando.','Choose Spanish or English and your gamepad type.'),
  ('keyboard','Escribe con el teclado integrado para mando.','Type with the built-in gamepad keyboard.'),
  ('list','Recorre la colección con mando, teclado o ratón.','Browse with a gamepad, keyboard or mouse.'),
  ('grid','Cambia de apariencia y abre los ajustes con atajos.','Use shortcuts to switch layouts and open settings.')]),
 ('07-actividad',('Tu historia de juego','Your play history'),[
  ('list','Consulta el tiempo jugado en la ficha de cada juego.','Check playtime in each game’s details.'),
  ('activity','Revisa las sesiones y cuándo jugaste por última vez.','Review sessions and when you last played.'),
  ('activity','Abre el historial desde el editor del juego.','Open the history from the game editor.'),
  ('playing','Configura qué hace Estante durante la partida.','Choose what Estante does while you play.')]),
 ('08-mientras-juegas',('Durante y entre partidas','During and between games'),[
  ('playing','Mantén Estante abierto o ciérralo y restáuralo.','Keep Estante open, or close and restore it.'),
  ('playing','También puedes elegir bandeja o salvapantallas.','You can also choose the tray or screensaver.'),
  ('screensaver','El salvapantallas recorre los fondos de tu biblioteca.','The screensaver cycles through your library backgrounds.'),
  ('background','Ajusta el fondo y la presentación a tu gusto.','Adjust the background and presentation to your taste.')]),
 ('09-instala-actualiza',('Listo para Linux','Ready for Linux'),[
  ('list','Disponible como AppImage para Linux x86_64.','Available as an AppImage for Linux x86_64.'),
  ('updates','El AppImage incluye Python, Qt y SDL2.','The AppImage includes Python, Qt and SDL2.'),
  ('updates','Busca actualizaciones desde los ajustes globales.','Check for updates in global settings.'),
  ('list','La biblioteca y tus ajustes se conservan al actualizar.','Your library and settings are preserved when updating.')]),
 ('10-imagenes-fichas',('Imágenes y fichas','Artwork and game details'),[
  ('artwork','Busca carátulas y logos con SteamGridDB.','Find covers and logos with SteamGridDB.'),
  ('imports','Configura IGDB para obtener fondos.','Configure IGDB to retrieve backgrounds.'),
  ('editor','Obtén fichas de Wikidata o edítalas a mano.','Get details from Wikidata or edit them by hand.'),
  ('artwork','También puedes usar imágenes locales o una URL.','You can also use local images or a URL.')]),
]
