"""Offline photo-scene forest quest. All scenes and navigation are fictional."""
from pathlib import Path
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle

ASSETS = Path(__file__).resolve().parent / 'assets' / 'forest_quest'
SCENES = {
 'trail': ('Лесная развилка', 'Тропа уходит между берёзами. Куда направимся?', 'trail', [('В ельник','spruce'),('К озеру','lake'),('На поляну','clearing')]),
 'spruce': ('Тихий ельник','Под корнями старых елей виднеется мох. Осмотритесь.', 'spruce',[('Осмотреть мох','find_spruce'),('Вернуться к развилке','trail')]),
 'lake': ('У лесного озера','На берегу тихо. В тени берёз может скрываться находка.', 'lake',[('Осмотреть берег','find_lake'),('На поляну','clearing'),('Назад','trail')]),
 'clearing': ('Солнечная поляна','Свет ложится на папоротники и мягкую подстилку.', 'clearing',[('Поискать грибы','find_clearing'),('В ельник','spruce'),('Назад','trail')]),
 'storm': ('Перед дождём','Небо потемнело. Лучше вернуться на знакомую тропу.', 'storm',[('К развилке','trail')]),
}
FINDS={'find_spruce':('Белый гриб',3),'find_lake':('Подберёзовик',2),'find_clearing':('Лисичка',2)}

def transition(scene, choice):
    if scene not in SCENES: raise ValueError('unknown scene')
    if choice not in [v for _,v in SCENES[scene][3]]: raise ValueError('invalid choice')
    return choice

class Quest:
 def __init__(self):
    self.scene='trail';self.found=set();self.popup=None
 def open(self):
    self.root=BoxLayout(orientation='vertical',padding=dp(8),spacing=dp(6))
    self.title=Label(size_hint_y=None,height=dp(42),bold=True,font_size=sp(19),color=(.9,.95,.87,1))
    self.photo=Image(allow_stretch=True,keep_ratio=False)
    self.description=Label(size_hint_y=None,height=dp(80),font_size=sp(14),halign='center',valign='middle',color=(.9,.94,.87,1))
    self.description.bind(size=lambda w,v:setattr(w,'text_size',(v[0]-dp(15),v[1])))
    self.actions=BoxLayout(orientation='vertical',size_hint_y=None,height=dp(150),spacing=dp(6))
    self.basket=Label(size_hint_y=None,height=dp(32),color=(.9,.85,.63,1))
    for w in (self.title,self.photo,self.description,self.actions,self.basket):self.root.add_widget(w)
    self.popup=Popup(title='Тихая охота · лесной квест',content=self.root,size_hint=(.97,.95),auto_dismiss=True,background_color=(.07,.13,.10,1))
    self.show();self.popup.open()
 def show(self):
    title,note,photo,choices=SCENES[self.scene]
    self.title.text=title;self.description.text=note
    self.photo.source=str(ASSETS/(photo+'.jpg'))
    self.actions.clear_widgets()
    for label,target in choices:
      btn=Button(text=label,font_size=sp(15),background_normal='',background_color=(.19,.40,.27,1))
      btn.bind(on_release=lambda _,t=target:self.choose(t));self.actions.add_widget(btn)
    self.basket.text='Корзинка: '+str(len(self.found))+' находок · Можно гулять без таймера'
 def choose(self,target):
    transition(self.scene,target)
    if target in FINDS:
      kind,points=FINDS[target]
      if target in self.found:message='Вы уже осматривали это место. Новых грибов здесь нет.'
      else:
        self.found.add(target);message=f'Вы нашли: {kind}! +{points} очка. В настоящем лесу проверяйте определение грибов.'
      Popup(title='Лесная находка',content=Label(text=message,halign='center',text_size=(dp(270),None)),size_hint=(.85,.32)).open()
      self.show();return
    self.scene=target;self.show()

def open_game(): Quest().open()
