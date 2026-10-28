"""Use the existing Spanish/English catalogue from QML as well as Python."""
from PySide6.QtCore import QTranslator
from i18n import tr, ENGLISH

ENGLISH.update({
    'Gestionar':'Manage','Gestión de Estante':'Manage Estante','Bandeja':'Tray',
    '+ Añadir':'+ Add','Editar ficha y categorías':'Edit information and categories',
    'Añadir / ejecución':'Add / launch','Imágenes y ficha online':'Artwork and online information',
    'Importación y scraping':'Import and scraping','Actividad':'Activity',
    'Título de la ficha':'Information title','Estudios · separados por comas':'Developers · comma separated',
    'Editoras · separadas por comas':'Publishers · comma separated','Géneros · separados por comas':'Genres · comma separated',
    'Plataformas · separadas por comas':'Platforms · comma separated','Categorías · separadas por comas':'Categories · comma separated',
    'Lanzamiento · DD/MM/AAAA o AAAA-MM-DD':'Release date · DD/MM/YYYY or YYYY-MM-DD',
    'Editar la ejecución del juego seleccionado':'Edit selected game launch configuration',
    'Nombre del juego':'Game name','Ejecutable .sh o .AppImage · ruta completa':'Executable .sh or .AppImage · full path',
    'Guardar ejecución':'Save launch configuration','Quitar juego seleccionado…':'Remove selected game…',
    'Confirmar: quitar de Estante':'Confirm: remove from Estante','Retirar imagen':'Remove artwork',
    'Intercambiar fondos':'Swap backgrounds','Elegir archivo…':'Choose file…',
    'Ruta local o URL de la imagen':'Local path or image URL','Capturas Steam':'Steam screenshots',
    'Ficha Wikidata':'Wikidata information','Fondo secundario':'Secondary background',
    'Importar juegos de Faugus':'Import Faugus games','Importar juegos de Steam':'Import Steam games',
    'Restaurar juegos excluidos':'Restore excluded games','Scraping de la biblioteca':'Scrape library',
    'Reemplazar imágenes y metadatos existentes':'Replace existing artwork and metadata',
    'Confirmar eliminación':'Confirm deletion','Categoría inicial':'Initial category',
    'Nombre de categoría':'Category name','Usar icono local':'Use local icon','Quitar icono':'Remove icon',
    'Buscar iconos':'Search icons','Buscar icono (en inglés)':'Search icons (in English)',
    'Ruta del icono local':'Local icon path','Instalar actualización del AppImage':'Install AppImage update',
    'Cancelar tareas':'Cancel tasks','Espacio':'Space','Borrar':'Backspace','Vaciar':'Clear','Listo':'Done',
    'Teclado · D-pad y A para escribir · B para cancelar':'Keyboard · D-pad and A to type · B to cancel',
    'Sin sinopsis disponible.':'No synopsis available.','Sin datos':'No data',
})


class Translator(QTranslator):
    def isEmpty(self): return False
    def translate(self, context, sourceText, disambiguation=None, n=-1):
        return tr(sourceText)
