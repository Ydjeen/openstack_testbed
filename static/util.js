function goTo(path, config_id = -1) {
    if (config_id === -1)
        config_id = document.getElementById('config_id').value
    if (path === '')
        window.location.href = '/configs/' + config_id
    if (path === 'rally')
        window.location.href = '/configs/' + config_id + '/rally_report'
    if (path === 'full_dump')
        window.location.href = '/configs/' + config_id + '/full_dump'
    if (path === 'log')
        window.location.href = '/configs/' + config_id
    if (path === 'destroy')
        window.location.href = '/configs/' + config_id + '/destroy'
    if (path === 'delete')
        window.location.href = '/configs/' + config_id + '/delete'
    if (path === 'redeploy')
        window.location.href = '/configs/' + config_id + '/redeploy'
    if (path === 'clean')
        window.location.href = '/configs/' + config_id + '/clean'
    if (path === 'run_experiment')
        window.location.href = '/configs/' + config_id + '/run_experiment'
    if (path === 'admin_openrc')
        window.location.href = '/configs/' + config_id + '/admin_openrc'
    if (path === 'test')
        window.location.href = '/configs/' + config_id + '/test'
}