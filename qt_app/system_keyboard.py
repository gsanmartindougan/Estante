"""Native keyboard requests with an optional in-app fallback; never installs packages."""
import os
import shutil
from PySide6.QtCore import QObject, Property, Signal, Slot, QProcess, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusPendingCallWatcher, QDBusMessage, QDBus
from shiboken6 import isValid
from i18n import tr
from qt_app.keyboard_config import provider, cosmic_connection_supported


class SystemKeyboard(QObject):
    changed = Signal()
    builtinRequested = Signal(QObject)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self._active = False
        self._notice = ''
        self._status = ''
        self._provider = ''
        self._process = None
        self._target = None
        self._fallback_override = None
        self._revision = 0
        self._verify = QTimer(self)
        self._verify.setSingleShot(True)
        self._verify.setInterval(1200)
        self._verify.timeout.connect(self.verify)
        self._input = QGuiApplication.inputMethod()
        self._input.visibleChanged.connect(self.visibilityChanged)
        self.refresh()

    @Property(bool, notify=changed)
    def active(self): return self._active

    @Property(str, notify=changed)
    def notice(self): return self._notice

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(QObject, notify=changed)
    def inputTarget(self): return self._target if self._target is not None and isValid(self._target) else None

    @Slot(QObject)
    def showFor(self, target):
        self._fallback_override=None
        self._target=target
        self.show()

    @Slot(QObject,str)
    @Slot(QObject,str,bool)
    def showForChoice(self, target, choice, fallback=None):
        self._fallback_override=fallback
        self._target=target
        self.showChoice(choice)

    def cosmic(self): return shutil.which('cosmic-osk')

    def cosmicSupport(self):
        if os.environ.get('LIBEI_SOCKET'): return True
        bus=QDBusConnection.sessionBus()
        if not bus.isConnected(): return None
        if bus.interface().isServiceRegistered('com.system76.CosmicComp').value(): return True
        if not bus.interface().isServiceRegistered('org.freedesktop.portal.Desktop').value(): return False
        message=QDBusMessage.createMethodCall('org.freedesktop.portal.Desktop',
                    '/org/freedesktop/portal/desktop','org.freedesktop.DBus.Introspectable','Introspect')
        reply=bus.call(message,QDBus.CallMode.Block,250)
        if reply.type()==QDBusMessage.MessageType.ErrorMessage: return None
        xml=reply.arguments()[0] if reply.arguments() else ''
        return cosmic_connection_supported([],str(xml))

    def cosmicUnavailable(self):
        desktop=os.environ.get('XDG_CURRENT_DESKTOP') or tr('Esta sesión')
        return tr('COSMIC OSK está instalado, pero la sesión actual ({desktop}) no ofrece la conexión de entrada que necesita: ni el servicio de COSMIC ni un portal RemoteDesktop con ConnectToEIS. Instalar cosmic-osk no añade ese soporte al compositor. Necesitas una sesión COSMIC u otro compositor y portal compatibles; no hay que reinstalar el teclado.').format(desktop=desktop)

    def kwin(self):
        bus=QDBusConnection.sessionBus()
        if not bus.isConnected(): return None
        # Never auto-start a compositor on a different desktop.
        if not bus.interface().isServiceRegistered('org.kde.KWin').value(): return None
        interface=QDBusInterface('org.kde.KWin','/VirtualKeyboard','org.kde.kwin.VirtualKeyboard',bus)
        interface.setTimeout(250)
        return interface if interface.isValid() and interface.property('available') else None

    def kdeUnavailable(self):
        desktop=os.environ.get('XDG_CURRENT_DESKTOP') or tr('Esta sesión')
        if any(name in desktop.lower() for name in ('kde','plasma')):
            return tr('Plasma Keyboard/Maliit está instalado, pero KWin no ofrece un teclado virtual activo. Selecciónalo y actívalo en los ajustes de teclado virtual de Plasma.')
        return tr('Plasma Keyboard/Maliit está instalado, pero esta sesión ({desktop}) no ofrece el servicio de teclado virtual de KWin que usa esta integración de Estante. El paquete utiliza input-method-v1; instalarlo no añade ese protocolo ni el servicio de KWin a tu compositor.').format(desktop=desktop)

    @Slot()
    def refresh(self):
        installed=[]
        if self.cosmic():
            installed.append('COSMIC (cosmic-osk)')
            if self.cosmicSupport() is False: installed.append(self.cosmicUnavailable())
        kde_installed=bool(shutil.which('maliit-keyboard') or shutil.which('plasma-keyboard'))
        if kde_installed:
            installed.append('Plasma Keyboard/Maliit (KDE)')
            if not self.kwin(): installed.append(self.kdeUnavailable())
        module=os.environ.get('QT_IM_MODULE','')
        if module: installed.append(tr('Método de entrada Qt: ')+module)
        self._status=(tr('Detectado: ')+', '.join(installed) if installed else
                      tr('No se ha detectado un teclado en pantalla instalado. Prueba primero el método del sistema. Si no aparece, instala cosmic-osk en un compositor compatible o activa el teclado virtual de KDE/Maliit en Plasma Wayland.'))
        self.changed.emit()

    def fail(self, text):
        self._verify.stop()
        self._active=False
        self._notice=text
        self._status=text
        use_fallback=self.controller.settings.get('keyboard_fallback',True) if self._fallback_override is None else self._fallback_override
        if use_fallback and self.inputTarget is not None and self._provider not in ('disabled','builtin'):
            self._notice=''
            self._status+='\n'+tr('Se usará el teclado de Estante como alternativa.')
            self.changed.emit()
            self.builtinRequested.emit(self._target)
        else:
            self.changed.emit()

    @Slot()
    def show(self):
        self.showChoice(self.controller.settings.get('onscreen_keyboard','auto'))

    @Slot(str)
    def showChoice(self, choice):
        if self._active: return
        self._verify.stop()
        self._revision+=1
        self._notice=''
        self._provider=choice
        if choice=='builtin':
            target=self.inputTarget or QGuiApplication.focusObject()
            if target is not None:
                self._status=tr('Teclado de Estante: escritura con mando dentro de la aplicación, sin depender del compositor.')
                self.changed.emit()
                self.builtinRequested.emit(target)
            else: self.fail(tr('Selecciona un campo de texto para abrir el teclado de Estante.'))
            return
        if choice=='disabled':
            self.fail(tr('El teclado en pantalla está desactivado. Puedes cambiarlo en Ajustes → Teclado.'))
            return
        kwin=self.kwin() if choice in ('auto','kde') else None
        cosmic=self.cosmic()
        desktop=os.environ.get('XDG_CURRENT_DESKTOP','').lower()
        choice=provider(choice,desktop=desktop,cosmic=bool(cosmic),kde=bool(kwin),wayland=bool(os.environ.get('WAYLAND_DISPLAY')))
        self._provider=choice
        self._active=True
        if choice=='cosmic':
            if not cosmic:
                self.fail(tr('No está instalado cosmic-osk. Instálalo y comprueba que tu compositor admite COSMIC OSK, o selecciona el teclado del sistema.'))
                return
            if self.cosmicSupport() is False:
                self.fail(self.cosmicUnavailable())
                return
            self._input.show()
            self.startCosmic(cosmic,'show')
        elif choice=='kde':
            if not kwin:
                self.fail(self.kdeUnavailable() if shutil.which('plasma-keyboard') or shutil.which('maliit-keyboard') else tr('No se detecta un teclado virtual activo de KDE. En Plasma Wayland, actívalo en los ajustes del sistema. En otro compositor comprueba primero su compatibilidad.'))
                return
            self._input.show()
            call=kwin.asyncCall('forceActivate')
            watcher=QDBusPendingCallWatcher(call,self)
            revision=self._revision
            def completed():
                if revision==self._revision and watcher.isError(): self.fail(tr('KDE no ha podido abrir el teclado virtual. Revisa su configuración en Plasma.'))
                watcher.deleteLater()
            watcher.finished.connect(completed)
            self._verify.start()
        else:
            self._input.show()
            self._verify.start()
        self.changed.emit()

    def startCosmic(self, program, action):
        # CLI show/hide are COSMIC's supported single-instance actions.
        process=QProcess(self)
        process.setProgram(program);process.setArguments([action])
        self._process=process
        diagnostics=[]
        def readErrors():
            diagnostics.append(bytes(process.readAllStandardError()).decode('utf-8','replace'))
            diagnostics[:]=[''.join(diagnostics)[-2000:]]
        process.readyReadStandardError.connect(readErrors)
        revision=self._revision
        def error(_):
            if revision==self._revision and action=='show': self.fail(tr('No se ha podido iniciar COSMIC OSK. Comprueba la instalación y la compatibilidad de tu compositor.'))
        def finished(code, _):
            if revision==self._revision and action=='show' and code!=0:
                readErrors()
                detail=''.join(diagnostics).strip()
                if 'ConnectToEIS' in detail or 'RemoteDesktop' in detail or 'Unable to find ei socket' in detail:
                    self.fail(self.cosmicUnavailable())
                else:
                    self.fail(tr('COSMIC OSK ha terminado sin abrirse.')+('\n'+detail[-1000:] if detail else ''))
            process.deleteLater()
            if self._process is process: self._process=None
        process.errorOccurred.connect(error);process.finished.connect(finished)
        process.start()
        if action=='show': self._status=tr('Solicitud enviada a COSMIC OSK. Usa su navegación con mando; pulsa Volver para continuar en Estante. Si no aparece, revisa la compatibilidad del compositor.')

    @Slot()
    def verify(self):
        if not self._active: return
        visible=self._input.isVisible()
        if self._provider=='kde':
            kwin=self.kwin()
            visible=visible or bool(kwin and kwin.property('visible'))
        if not visible:
            self.fail(tr('El sistema no ha mostrado un teclado en pantalla. Revisa la compatibilidad y la configuración en Ajustes → Globales → Teclado. COSMIC necesita una conexión EI y Plasma un teclado virtual activo de KWin; instalar sus paquetes no proporciona esas funciones a otro compositor.'))
        else:
            self._status=tr('Teclado del sistema abierto.')
            self.changed.emit()

    @Slot()
    def visibilityChanged(self):
        if self._input.isVisible():
            self._verify.stop()
            self._active=True
            self._notice=''
        elif self._provider in ('system','kde'):
            self._active=False
        self.changed.emit()

    @Slot()
    def hide(self):
        self._revision+=1
        self._verify.stop()
        was_active=self._active
        self._input.hide()
        if was_active and self._provider=='kde':
            kwin=self.kwin()
            if kwin: kwin.setProperty('active',False)
        if was_active and self._provider=='cosmic' and self.cosmic(): self.startCosmic(self.cosmic(),'hide')
        self._active=False
        self._notice=''
        self._target=None
        self._fallback_override=None
        self.changed.emit()
