
1.不要定义新的异常，用/home/dustp/codes/idproject/idbackend/src/app/schemas/errors.py的通用异常就好

2./home/dustp/codes/idproject/idbackend/src/app/response.py和/home/dustp/codes/idproject/idbackend/src/app/schemas/page.py是公告封装好的返回体

3.Request,Response,VO,DTO等数据结构体在schema封装好/home/dustp/codes/idproject/idbackend/src/app/schemas，
互相的转换也在schema封装好对应方法，不要在别的地方比route,service,repo等进行数据结构体的转换

4./home/dustp/codes/idproject/idbackend/src/app/routes，
不要在route层做任何数据库相关操作，也不做从contextvar获取数据等操作
route层只做接收接口数据，传递给service，返回对应数据，
所有数据库操作、contextvar操作，业务逻辑下沉到service层/home/dustp/codes/idproject/idbackend/src/services

5.service层如果有复杂的ORM操作，将数据库的操作放到repositories，/home/dustp/codes/idproject/idbackend/src/repositories



6.token和rbac的鉴权以及异常捕获已经在中间件做好，避免重复/home/dustp/codes/idproject/idbackend/src/app/middleware