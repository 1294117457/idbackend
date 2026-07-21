@idbackend/src/agent 我要实现一个agent,主要功能就是
1.一个对话功能，用户可以通过对话快速了解系统使用方法，这就是后续总结一个功能文档，然后上传到知识向量库
2.用户提交自己的证明材料或者通过对话形势，快速给用户定位可以选择的template对应的条件，具体是，用户上传材料或者对话，agent帮助匹配到可能的template并结合和对应的条件，列举出然后让用户选择，然后用户上传材料，就是列举出来，用户选择合适的直接到@idfrontend/src/views/template/components/StepBar.vue @idfrontend/src/views/template/components/TemplateApplyDialog.vue 这里的第二步，

总体是用langgraph,结合不同的node和interrupt,然后还有rag知识库，用于agent知道政策文档，并且要能调取template的接口获取现在template的情况@idbackend/src/app/routes/template.py ，template情况结合政策文件结合用户给的信息匹配出用户最合适的template,

这里你觉得怎么做合适呢，比如
1.上传材料时识别要用什么
2node设计那些合适
3rag怎么做
4上传材料后interrupt返回可能的template列表给用户选择怎么做
5sse对话怎么做
6前端具体对话原本是一个悬浮框，帮助匹配template是一块功能区，这里你觉得怎么做合适呢

帮我分析下，暂时不修改代码




总的就是前端实现对应UI,
postgre提供向量数据库，
langgraph实现llm接入，node定义，graph编排，
rag搭建，ocr解析，向量块存储，
fastApi实现接口路由，schema结构体定义
更多的对话持久化、前端管理向量库crud
对吗

@idbackend/docs/step2/agent在这目录下给我生成对应文档 一个总体的目录文档，大致介绍分哪几步，每步再有具体的开发文档