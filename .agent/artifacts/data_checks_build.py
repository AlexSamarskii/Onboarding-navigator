from pathlib import Path
import json, difflib
import yaml
root=Path.cwd()
a=root/'.agent/artifacts'
snap=json.loads((a/'data_scope_snapshot.json').read_text())
def put(p,s):
 assert p in snap['allowed_paths'],p
 f=root/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(s,encoding='utf-8')
for mode in ['it_support','benefits','learning','culture','onboarding_plan']:
 if mode=='it_support': d=yaml.safe_load(snap['before'][f'config/modes/{mode}/mode.yaml'])
 else:d={'name':mode,'display_name':f'mode.{mode}','description':'Обезличенный демонстрационный режим HR-поддержки; не реальная политика компании.','enabled':True,'files':{'system_prompt':'system_prompt.md','faq':'faq.md'},'timeout_seconds':30}
 d['display_name']=f'mode.{mode}'
 d['source_titles']={'faq.md':f'mode.{mode}','system_prompt.md':f'mode.{mode}'}
 if mode=='it_support':d['diagnostics_file']='diagnostics.yaml'
 if mode=='culture':d['source_titles']['policies/example.md']='mode.culture'
 if mode=='onboarding_plan':
  d['plans_directory']='plans'
  for n in ['developer','developer__engineering','default']:d['source_titles'][f'plans/{n}.md']='mode.onboarding_plan'
 put(f'config/modes/{mode}/mode.yaml',yaml.safe_dump(d,allow_unicode=True,sort_keys=False))
 prompt=(snap['before'][f'config/modes/{mode}/system_prompt.md'] if mode=='it_support' else 'Ты помощник Onboarding Navigator по вопросам сотрудников.\n')
 prompt+='''\nИспользуй только переданный контекст FAQ, планов и политик выбранного режима.
Все материалы этого bundle — обезличенные демонстрационные примеры, не реальные правила работодателя. Явно сообщай об этом при ответе.
Не придумывай факты, контакты, суммы, ссылки и цитаты. Если подтверждения нет, сообщи об отсутствии ответа и предложи эскалацию.
Не запрашивай пароли и токены, не выполняй команды, покупки или изменения HR-данных.
Не утверждай, что заявка создана, пока адаптер не подтвердил создание. Данные профиля сообщает пользователь; доступа к HR-системе нет.
Для цитирования используй только дословный фрагмент реально переданного контекста; не выдумывай источник.
'''
 if mode=='it_support':prompt+='Диагностические вопросы задаёт только детерминированный YAML-диалог; не сочиняй дополнительные развилки.\n'
 if mode=='onboarding_plan':prompt+='Выбирай предоставленный план роли/отдела; не выдумывай отсутствующий план и не сохраняй прогресс чеклиста.\n'
 put(f'config/modes/{mode}/system_prompt.md',prompt)
notice='> Обезличенные демонстрационные данные для acceptance-тестов. Это не реальные политики компании. Контакты, ссылки и числовые правила — тестовые примеры.\n'
facts={
'it_support': [('vpn-connect','Как подключиться к VPN?','Демо-инструкция: используйте корпоративный клиент VPN из https://it.example.invalid/vpn. Если клиент не установлен или соединение не работает, обратитесь в контакт IT: it@example.invalid. Если подключение работает, дополнительных действий не требуется.'),('mail-delivery','Не приходит письмо на корпоративную почту','Демо-инструкция: проверьте папку «Спам» и квоту почтового ящика. Если письмо найдено в спаме, отметьте его как нужное; при заполненной квоте уточните очистку у IT; если письма нет и квота свободна, обратитесь в контакт IT: it@example.invalid.'),('git-access','Как получить доступ к Git?','Демо-инструкция: оформите заявку на Git-доступ через https://it.example.invalid/access и получите согласование руководителя. Контакт IT: it@example.invalid.')],
'benefits':[('medical-insurance','Какие льготы по ДМС?','Демо-правило: полис ДМС доступен после оформления у HR. Для получения полиса обратитесь в HR-контакт: hr@example.invalid.'),('vacation','Сколько дней отпуска?','Демо-правило: ежегодный отпуск составляет 28 календарных дней. Это тестовое число, не реальная политика работодателя; уточнения — hr@example.invalid.'),('sick-leave','Как оформить больничный?','Демо-шаги: получите электронный больничный у врача, сообщите о периоде отсутствия руководителю и передайте сведения HR. HR-контакт: hr@example.invalid.')],
'learning':[('course-catalog','Какие курсы доступны?','Демо-каталог курсов: https://learning.example.invalid/catalog. Выберите курс из каталога.'),('training-approval','Как согласовать обучение?','Демо-шаги согласования: выберите курс, отправьте руководителю цель и стоимость, дождитесь согласования, затем передайте заявку HR: hr@example.invalid.'),('training-budget','Есть ли бюджет на обучение?','Демо-правило: лимит обучения — 10000 условных единиц на сотрудника за календарный год после согласования руководителя. Это вымышленный тестовый лимит, не обещание выплаты.')],
'culture':[('work-hours','Какой график работы?','Демо-правило: гибкий график с общими часами связи 11:00–16:00; конкретное время согласуйте с руководителем.'),('dress-code','Есть ли дресс-код?','Демо-правило: повседневный аккуратный дресс-код; требования безопасности рабочего места обязательны.'),('business-trip','Как оформить командировку?','Демо-шаги: согласуйте цель и даты с руководителем, направьте заявку HR и дождитесь подтверждения. HR-контакт: hr@example.invalid.')],
'onboarding_plan':[('profile','Как указать роль и отдел?','Сообщите роль и отдел через /start или при первом обращении к плану; сведения предназначены для сессии на 24 часа, доступа к HR-системе нет.'),('plan-selection','Как выбирается план онбординга?','Сначала выбирается plans/<role>__<department>.md, затем plans/<role>.md. Для тестового профиля developer/engineering приоритетен developer__engineering.md.'),('missing-plan','Что делать, если план не настроен?','Если план не настроен, бот сообщает об этом, предлагает plans/default.md при наличии и эскалацию по подтверждению пользователя; выдуманный персональный план не выдаётся.')]
}
for mode,entries in facts.items():
 start=snap['before'][f'config/modes/{mode}/faq.md'] if mode=='it_support' else f'# FAQ: {mode}\n'
 text=start+'\n'+notice
 for anchor,question,answer in entries:text+=f'\n<a id="{anchor}"></a>\n## {question}\n{answer}\n'
 put(f'config/modes/{mode}/faq.md',text)
put('config/modes/culture/policies/example.md','# Пример корпоративной политики\n\n'+notice+'\nГибкий график: общие часы связи 11:00–16:00, остальное время согласуется с руководителем. Повседневный аккуратный дресс-код; требования безопасности обязательны. Командировка: согласовать цель и даты, направить заявку HR (hr@example.invalid), дождаться подтверждения.\n')
plans={
'developer':['Уточнить у руководителя задачи роли разработчика.','Изучить демо-FAQ по VPN и Git; оформить доступы через утверждённый процесс.','Согласовать первую учебную задачу и ревью с наставником.'],
'developer__engineering':['Уточнить у руководителя engineering задачи и наставника.','Прочитать демо-FAQ по VPN и Git; согласовать доступ к учебному репозиторию engineering.','Обсудить с наставником правила ревью команды engineering.'],
'default':['Уточнить роль, отдел и наставника у руководителя.','Ознакомиться с демо-FAQ по IT, льготам и культуре.','Попросить уточнение персонального плана через эскалацию.']}
for name,steps in plans.items():put(f'config/modes/onboarding_plan/plans/{name}.md',f'# Чеклист: {name}\n\n'+notice+'\n'+'\n'.join('- [ ] '+s for s in steps)+'\n')
def esc(kind):return {'label_key':f'diagnostics.{kind}.escalation','action':'escalate'}
def terminal(kind,label,ref):return {'type':'terminal','label_key':f'diagnostics.{kind}.{label}','faq_ref':'faq.md#'+ref,'escalation':esc(kind)}
def question(kind,key,choices):return {'type':'question','question_key':f'diagnostics.{kind}.{key}','choices':[{'label_key':f'diagnostics.{kind}.{label}','next':nxt} for label,nxt in choices],'escalation':esc(kind)}
diag={'version':1,'scenarios':{
'vpn':{'title_key':'diagnostics.vpn.title','start':'client','nodes':{
'client':question('vpn','client_question',[('client_installed','connection'),('client_missing','install')]),
'connection':question('vpn','connection_question',[('connected','ready'),('connection_failed','contact')]),
'install':terminal('vpn','client_missing','vpn-connect'),'ready':terminal('vpn','connected','vpn-connect'),'contact':terminal('vpn','connection_failed','vpn-connect')}},
'mail':{'title_key':'diagnostics.mail.title','start':'spam','nodes':{
'spam':question('mail','spam_question',[('spam_found','found'),('spam_missing','quota')]),
'quota':question('mail','quota_question',[('quota_full','full'),('quota_available','contact')]),
'found':terminal('mail','spam_found','mail-delivery'),'full':terminal('mail','quota_full','mail-delivery'),'contact':terminal('mail','quota_available','mail-delivery')}}}}
put('config/modes/it_support/diagnostics.yaml',yaml.safe_dump(diag,allow_unicode=True,sort_keys=False))
patch=''
for path,before in snap['before'].items():
 after=(root/path).read_text()
 patch+=''.join(difflib.unified_diff((before or '').splitlines(True),after.splitlines(True),fromfile='a/'+path if before is not None else '/dev/null',tofile='b/'+path))
(a/'patch.diff').write_text(patch)
print('Written',len(snap['allowed_paths']),'product files; patch generated')
